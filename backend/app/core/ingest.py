"""Raw -> normalized CaseRecord: messy CSV/JSON in, typed case out."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .normalize import AMOUNT_FORMATS, AmountFormatError, norm_phone, parse_amount_strict, parse_ts
from .schemas import CaseRecord, Transaction

# header aliases seen in real exports (EN/RU/local)
_ALIASES = {
    "id": "id", "txid": "id", "transaction_id": "id", "номер": "id",
    "ts": "ts", "date": "ts", "datetime": "ts", "timestamp": "ts", "дата": "ts",
    "amount": "amount", "sum": "amount", "value": "amount", "сумма": "amount",
    "direction": "direction", "type": "direction", "dr_cr": "direction",
    "from": "from_name", "sender": "from_name", "from_name": "from_name",
    "counterparty": "counterparty_name", "counterparty_name": "counterparty_name",
    "to": "to_name", "recipient": "to_name", "to_name": "to_name",
    "from_account": "from_account", "sender_account": "from_account", "account": "from_account",
    "to_account": "to_account", "receiver_account": "to_account",
    "from_kind": "from_kind", "to_kind": "to_kind", "kind": "counterparty_kind",
    "counterparty_kind": "counterparty_kind",
    "channel": "channel", "system": "channel", "тип операции": "channel",
    "memo": "memo", "note": "memo", "purpose": "memo", "назначение": "memo",
    "phone": "phone", "телефон": "phone",
    "geo": "geo", "city": "geo", "город": "geo",
}


def _canon_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        key = _ALIASES.get(str(k).strip().lower(), str(k).strip().lower())
        out[key] = v
    return out


_DIR_IN = {"in", "credit", "c", "cr", "incoming", "inbound", "приход", "зачисление", "+"}
_DIR_OUT = {"out", "debit", "d", "dr", "outgoing", "outbound", "расход", "списание", "-"}
_KIND_BUSINESS = {"business", "company", "legal", "mchj", "mkk", "ooo", "ип", "ip", "чп", "юр", "бизнес"}
_KIND_PERSON = {"person", "individual", "физ", "физлицо", "private"}
CHANNELS = ("p2p", "cash_in", "cash_out", "atm", "card", "pos", "merchant", "wire")
# generated casebook records use the generator's documented convention
# (data/generator/generate.py: "1.234.567" = dot-grouped thousands)
CASEBOOK_SPLITS = {"train", "test", "novel", "demo"}


def _dir(value: Any) -> str | None:
    v = str(value or "").strip().lower()
    if v in _DIR_IN:
        return "in"
    if v in _DIR_OUT:
        return "out"
    return None


def _kind(value: Any) -> str | None:
    """Counterparty kind; '' -> None (not provided), unknown text -> ValueError."""
    v = str(value or "").strip().lower()
    if not v:
        return None
    if v == "subject":
        return "subject"
    if v in _KIND_PERSON:
        return "person"
    if v in _KIND_BUSINESS:
        return "business"
    raise ValueError(v)


class InputValidationError(ValueError):
    """Row-level input problems with stable, human-readable messages."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        shown = "; ".join(errors[:6])
        if len(errors) > 6:
            shown += f" (+{len(errors) - 6} more)"
        super().__init__(shown)


def _kind_checked(row: dict[str, Any], key: str, n: int, row_errs: list[str],
                  notes: dict[str, int]) -> str:
    try:
        k = _kind(row.get(key))
    except ValueError as e:
        row_errs.append(f"row {n}: {key} '{str(e)[:20]}' not recognised (use person/business)")
        return "person"
    if k is None:
        notes["kind_missing"] += 1
        return "person"
    return k


def _today_tashkent() -> date:
    return datetime.now(ZoneInfo("Asia/Tashkent")).date()


def _opt_int(v: Any) -> int | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return int(v)


def _opt_float(v: Any) -> float | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return float(v)


def normalize_case(raw: dict[str, Any], amount_format: str | None = None,
                   today: date | None = None) -> CaseRecord:
    """Validate and normalize a case dict (generated casebook or parsed CSV).

    Nothing is silently substituted: every row problem is collected and raised
    as InputValidationError with row numbers. Rules:
      - amount: parse_amount_strict in the chosen format (casebook records use
        the generator's dot-thousands convention, everything else 'strict');
      - date: must parse and must not be after the analysis date
        (Asia/Tashkent calendar day) — future-dated rows are rejected;
      - direction: must be a known in/out token;
      - channel: one of CHANNELS; an absent/empty value becomes 'unknown' and
        is reported in warnings, an unrecognised value is an error;
      - counterparty name: required; counterparty kind: person/business, an
        absent value defaults to person and is reported in warnings;
      - ids: when an id column is present every id must be non-empty and unique.
    Missing subject metadata (account age, declared turnover) stays None.
    """
    fmt = amount_format or raw.get("amount_format") or (
        "dot-thousands" if raw.get("split") in CASEBOOK_SPLITS else "strict")
    if fmt not in AMOUNT_FORMATS:
        raise InputValidationError([f"unknown amount format '{fmt}' (use one of {', '.join(AMOUNT_FORMATS)})"])
    today = today or _today_tashkent()
    parsed_rows: list[tuple[int, object, Transaction]] = []
    errors: list[str] = []
    notes: dict[str, int] = {"channel_missing": 0, "kind_missing": 0}
    seen_ids: dict[str, int] = {}
    subj_acct = str(raw.get("subject_account") or "SUBJ")
    subj_name = str(raw.get("subject_name") or "Subject account")
    rows = raw.get("transactions", [])
    has_id_col = any("id" in _canon_row(r) for r in rows[:1])
    for i, row in enumerate(rows):
        n = i + 1
        row = _canon_row(row)
        row_errs: list[str] = []
        ts_raw = str(row.get("ts") or "").strip()
        dt = parse_ts(ts_raw)
        if not ts_raw:
            row_errs.append(f"row {n}: date is missing")
        elif dt is None:
            row_errs.append(
                f"row {n}: date '{ts_raw[:30]}' not recognised "
                "(expected ISO yyyy-mm-dd[ hh:mm[:ss]], dd.mm.yyyy[ hh:mm], dd/mm/yyyy[ hh:mm])")
        elif dt.date() > today:
            row_errs.append(f"row {n}: date {dt.date()} is after the analysis date {today} "
                            "(future-dated transactions are rejected)")
        try:
            amount = parse_amount_strict(row.get("amount") if row.get("amount") is not None else "", fmt)
        except AmountFormatError as e:
            txt = str(row.get("amount") or "").strip()
            row_errs.append(f"row {n}: amount '{txt[:40]}': {e}" if txt else f"row {n}: amount is missing")
            amount = 0.0
        direction = _dir(row.get("direction"))
        if direction is None:
            d = str(row.get("direction") or "").strip()
            row_errs.append(f"row {n}: direction '{d[:20]}' not recognised (use in/out, credit/debit, приход/расход)"
                            if d else f"row {n}: direction is missing")
        if has_id_col:
            rid = str(row.get("id") or "").strip()
            if not rid:
                row_errs.append(f"row {n}: transaction id is empty")
            elif rid in seen_ids:
                row_errs.append(f"row {n}: duplicate transaction id '{rid[:30]}' (also row {seen_ids[rid]})")
            else:
                seen_ids[rid] = n
        else:
            rid = f"row-{n}"
        channel_raw = str(row.get("channel") or "").strip().lower()
        if not channel_raw or channel_raw == "unknown":  # "unknown" = explicit marker
            channel = "unknown"
            notes["channel_missing"] += 1
        elif channel_raw in CHANNELS:
            channel = channel_raw
        else:
            channel = "unknown"
            row_errs.append(f"row {n}: channel '{channel_raw[:20]}' not recognised (use {', '.join(CHANNELS)})")

        if "counterparty_name" in row:  # counterparty-centric rows (jury template)
            cp_name = str(row.get("counterparty_name") or "").strip()
            if not cp_name:
                row_errs.append(f"row {n}: counterparty_name is missing")
            cp_kind = _kind_checked(row, "counterparty_kind", n, row_errs, notes)
            if direction == "out":
                frm = (subj_name, "subject", subj_acct)
                to = (cp_name, cp_kind, str(row.get("to_account") or f"cp-{i}"))
            else:
                frm = (cp_name, cp_kind, str(row.get("from_account") or f"cp-{i}"))
                to = (subj_name, "subject", subj_acct)
        else:
            fn, tn = str(row.get("from_name") or "").strip(), str(row.get("to_name") or "").strip()
            if not fn:
                row_errs.append(f"row {n}: from_name is missing")
            if not tn:
                row_errs.append(f"row {n}: to_name is missing")
            frm = (fn, _kind_checked(row, "from_kind", n, row_errs, notes), str(row.get("from_account") or f"acct-a-{i}"))
            to = (tn, _kind_checked(row, "to_kind", n, row_errs, notes), str(row.get("to_account") or f"acct-b-{i}"))
            # subject side: generated cases mark subject as kind=subject / name=SUBJ
            if frm[1] == "subject" or frm[0] == "SUBJ":
                frm = (subj_name, "subject", subj_acct)
            if to[1] == "subject" or to[0] == "SUBJ":
                to = (subj_name, "subject", subj_acct)
        if row_errs:
            errors.extend(row_errs)
            continue
        tx = Transaction(
            id=rid, ts=dt.isoformat(), amount=amount,
            direction=direction,  # type: ignore[arg-type]
            from_account=frm[2], from_name=frm[0], from_kind=frm[1],  # type: ignore[arg-type]
            to_account=to[2], to_name=to[0], to_kind=to[1],  # type: ignore[arg-type]
            channel=channel,  # type: ignore[arg-type]
            memo=str(row.get("memo") or ""),
            phone=norm_phone(str(row.get("phone") or "")),
            geo=str(row.get("geo") or ""),
        )
        parsed_rows.append((i, dt, tx))
    if errors:
        raise InputValidationError(errors)
    parsed_rows.sort(key=lambda r: (r[1], r[0]))  # stable chronological order
    txs = [r[2] for r in parsed_rows]

    try:
        age = _opt_int(raw.get("account_age_days"))
        turnover = _opt_float(raw.get("declared_turnover_monthly"))
    except (TypeError, ValueError) as e:
        raise InputValidationError([f"subject metadata is not numeric: {e}"]) from e
    # notes survive re-normalisation of an already-normalised case
    input_notes: list[str] = list(raw.get("input_notes") or [])

    def note(text: str) -> None:
        if text not in input_notes:
            input_notes.append(text)

    if notes["channel_missing"]:
        note(f"channel not provided on {notes['channel_missing']} row(s) — recorded as "
                           "'unknown'; cash/channel features and rules ignore those rows")
    if notes["kind_missing"]:
        note(f"counterparty kind not provided on {notes['kind_missing']} row(s) — treated as person")
    opened = parse_ts(str(raw.get("opened_at") or ""))
    if opened is not None:
        late = sum(1 for _, d, _ in parsed_rows if d > opened)
        if late:
            note(f"{late} transaction(s) dated after the case opening date "
                               f"{opened.date()} — included in the analysis")
    case = CaseRecord(
        case_id=str(raw.get("case_id") or "JURY-INPUT"),
        subject_account=subj_acct,
        subject_name=subj_name,
        subject_kind=raw.get("subject_kind") or "person",  # type: ignore[arg-type]
        account_age_days=age,
        declared_turnover_monthly=turnover,
        branch=str(raw.get("branch") or ""),
        alert_source=str(raw.get("alert_source") or "jury-input"),
        opened_at=str(raw.get("opened_at") or ""),
        transactions=txs,
        labels=list(raw.get("labels") or []),
        is_suspicious=bool(raw.get("is_suspicious", False)),
        split=str(raw.get("split") or "jury"),
        generator_variant=str(raw.get("generator_variant") or "base"),
        input_notes=input_notes,
        amount_format=fmt,
    )
    return case


def case_from_csv(text: str, case_id: str = "JURY-INPUT", amount_format: str = "strict") -> CaseRecord:
    """Parse an analyst/jury CSV (RU/EN headers). Raises InputValidationError."""
    sample = text[:4096]
    try:
        dialect: csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]
    reader = csv.DictReader(io.StringIO(text.strip()), dialect=dialect)  # type: ignore[arg-type]
    rows = list(reader)
    if not rows:
        raise InputValidationError(["CSV has no data rows"])
    cols = {_ALIASES.get(str(k).strip().lower(), str(k).strip().lower()) for k in (reader.fieldnames or [])}
    missing = [c for c in ("ts", "amount", "direction") if c not in cols]
    if "counterparty_name" not in cols and not {"from_name", "to_name"} <= cols:
        missing.append("counterparty_name (or from_name + to_name)")
    if missing:
        raise InputValidationError([f"missing required column(s): {', '.join(missing)}"])
    raw = {"case_id": case_id, "transactions": rows}
    return normalize_case(raw, amount_format=amount_format)


def case_from_jsonl_line(line: str) -> dict[str, Any]:
    return json.loads(line)
