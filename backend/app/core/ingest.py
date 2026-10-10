"""Raw -> normalized CaseRecord: messy CSV/JSON in, typed case out."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from .normalize import norm_phone, parse_amount, parse_ts
from .schemas import CaseRecord, Transaction

# header aliases seen in real exports (EN/RU/local)
_ALIASES = {
    "id": "id", "txid": "id", "transaction_id": "id", "номер": "id",
    "ts": "ts", "date": "ts", "datetime": "ts", "timestamp": "ts", "дата": "ts",
    "amount": "amount", "sum": "amount", "value": "amount", "сумма": "amount",
    "direction": "direction", "type": "direction", "dr_cr": "direction",
    "from": "from_name", "sender": "from_name", "from_name": "from_name",
    "counterparty": "from_name", "counterparty_name": "counterparty_name",
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


def _dir(value: str) -> str:
    v = str(value).strip().lower()
    if v in {"in", "credit", "c", "incoming", "inbound", "приход", "зачисление", "+", "1"}:
        return "in"
    if v in {"out", "debit", "d", "outgoing", "outbound", "расход", "списание", "-", "0"}:
        return "out"
    return "in" if v.startswith(("in", "c", "п", "з")) else "out"


def _kind(value: str, default: str = "person") -> str:
    v = str(value or "").strip().lower()
    if any(w in v for w in ("mchj", "mkk", "ooo", "бизнес", "business", "ip", "чп", "company")):
        return "business"
    return default if v in ("", "person", "физ", "individual") else "person"


def normalize_case(raw: dict[str, Any]) -> CaseRecord:
    """Accepts a generated-case dict (with messy strings) or an API payload."""
    txs: list[Transaction] = []
    parsed_rows: list[tuple[int, object, Transaction]] = []
    for i, row in enumerate(raw.get("transactions", [])):
        row = _canon_row(row)
        ts_raw = str(row.get("ts", ""))
        dt = parse_ts(ts_raw)
        ts_iso = dt.isoformat() if dt else ""
        amount = parse_amount(row.get("amount", 0))
        direction = _dir(str(row.get("direction", "in")))
        rid = str(row.get("id") or f"row-{i + 1}")
        subj_acct = str(raw.get("subject_account", "SUBJ"))
        subj_name = str(raw.get("subject_name", "SUBJ"))
        # counterparty-centric rows (jury template)
        if "counterparty_name" in row:
            cp_name = str(row.get("counterparty_name", ""))
            cp_kind = _kind(str(row.get("counterparty_kind", "")))
            if direction == "in":
                frm = (cp_name, cp_kind, str(row.get("from_account") or f"cp-{i}"), True)
                to = (subj_name, "subject", subj_acct, False)
            else:
                frm = (subj_name, "subject", subj_acct, False)
                to = (cp_name, cp_kind, str(row.get("to_account") or f"cp-{i}"), True)
        else:
            frm = (
                str(row.get("from_name", "")),
                _kind(str(row.get("from_kind", ""))),
                str(row.get("from_account") or f"acct-a-{i}"),
                False,
            )
            to = (
                str(row.get("to_name", "")),
                _kind(str(row.get("to_kind", ""))),
                str(row.get("to_account") or f"acct-b-{i}"),
                False,
            )
            # subject side: generated cases mark subject as kind=subject / name=SUBJ
            if frm[1] == "subject" or frm[0] == "SUBJ":
                frm = (subj_name, "subject", subj_acct, False)
            if to[1] == "subject" or to[0] == "SUBJ":
                to = (subj_name, "subject", subj_acct, False)
        channel = str(row.get("channel") or "p2p").strip().lower()
        if channel not in {"p2p", "cash_in", "cash_out", "atm", "card", "pos", "merchant", "wire"}:
            channel = "p2p"
        tx = Transaction(
            id=rid,
            ts=ts_iso,
            amount=amount,
            direction=direction,  # type: ignore[arg-type]
            from_account=frm[2],
            from_name=frm[0],
            from_kind=frm[1],  # type: ignore[arg-type]
            to_account=to[2],
            to_name=to[0],
            to_kind=to[1],  # type: ignore[arg-type]
            channel=channel,  # type: ignore[arg-type]
            memo=str(row.get("memo") or ""),
            phone=norm_phone(str(row.get("phone") or "")),
            geo=str(row.get("geo") or ""),
        )
        parsed_rows.append((i, dt, tx))
    # stable chronological sort; unparsed keep input order at the end
    parsed_rows.sort(key=lambda r: (r[1] is None, r[1] or 0, r[0]))
    txs = [r[2] for r in parsed_rows]

    case = CaseRecord(
        case_id=str(raw.get("case_id") or "JURY-INPUT"),
        subject_account=str(raw.get("subject_account") or "SUBJ"),
        subject_name=str(raw.get("subject_name") or "Subject account"),
        subject_kind=raw.get("subject_kind") or "person",  # type: ignore[arg-type]
        account_age_days=int(raw.get("account_age_days") or 400),
        declared_turnover_monthly=float(raw.get("declared_turnover_monthly") or 0),
        branch=str(raw.get("branch") or ""),
        alert_source=str(raw.get("alert_source") or "jury-input"),
        opened_at=str(raw.get("opened_at") or ""),
        transactions=txs,
        labels=list(raw.get("labels") or []),
        is_suspicious=bool(raw.get("is_suspicious", False)),
        split=str(raw.get("split") or "jury"),
        generator_variant=str(raw.get("generator_variant") or "base"),
    )
    return case


def case_from_csv(text: str, case_id: str = "JURY-INPUT") -> CaseRecord:
    """Parse a jury-provided CSV (RU/EN headers, messy amounts/dates)."""
    sample = text[:4096]
    try:
        dialect: csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]
    reader = csv.DictReader(io.StringIO(text.strip()), dialect=dialect)  # type: ignore[arg-type]
    rows = list(reader)
    if not rows:
        raise ValueError("CSV has no data rows")
    raw = {"case_id": case_id, "transactions": rows}
    # optional metadata rows as comments are dropped by DictReader
    case = normalize_case(raw)
    if not case.transactions:
        raise ValueError("No parseable transactions found — check the header row")
    return case


def case_from_jsonl_line(line: str) -> dict[str, Any]:
    return json.loads(line)
