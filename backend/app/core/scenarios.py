"""Deterministic typology scenario library (the explainable rule layer).

Each rule mirrors how an L1 analyst at the alert desk reasons, and is mapped
to public AML/CFT typology families (FATF). Rules produce evidence (tx ids)
that the narrative cites — a score without these hits would be
unexplainable, which the CBU audit process does not accept.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .features import REPORTING_THRESHOLD
from .normalize import memo_hits, parse_ts
from .schemas import CaseRecord, ScenarioHit

RULES_DOC = {
    "SC-01": "Cash structuring: repeated deposits just below the UZS 50,000,000 cash-reporting threshold from multiple senders (FATF: structuring / smurfing).",
    "SC-02": "Rapid pass-through: >70% of each inflow leaves the account again within 24 hours; balance stays near zero (FATF: layering / rapid movement of funds).",
    "SC-03": "Mule fan-in: many unrelated individuals paying a young account, then consolidation withdrawal (money-mule typology).",
    "SC-04": "Crypto off-ramp: fan-in from individuals with USDT/crypto memos, consolidated payout to a crypto counterparty or cash (FATF: virtual-asset abuse).",
    "SC-05": "Counterparty cycle: counterparties of the subject transact with each other, forming triangles — layered routing (FATF: layered transactions).",
    "SC-06": "Turnover mismatch: 90-day inflow several times the declared monthly turnover on file (standard CBU KYC/monitoring check).",
}


def _subject_cp_names(case: CaseRecord) -> set[str]:
    names = set()
    for t in case.transactions:
        if t.from_kind != "subject" and t.from_name and t.from_name != "SUBJ":
            names.add(t.from_name.strip().lower())
        if t.to_kind != "subject" and t.to_name and t.to_name != "SUBJ":
            names.add(t.to_name.strip().lower())
    return names


def run_scenarios(case: CaseRecord) -> list[ScenarioHit]:
    txs = case.transactions
    hits: list[ScenarioHit] = []
    T = REPORTING_THRESHOLD

    ins = [t for t in txs if t.direction == "in"]
    outs = [t for t in txs if t.direction == "out"]
    dts = {t.id: (parse_ts(t.ts) or datetime(2026, 1, 1)) for t in txs}
    total_in = sum(t.amount for t in ins)
    total_out = sum(t.amount for t in outs)

    def cp(t):
        return (t.from_account or t.from_name) if t.direction == "in" else (t.to_account or t.to_name)

    # SC-01 structuring
    jb = [t for t in ins if 0.85 * T <= t.amount < T]
    senders = {cp(t) for t in jb}
    if len(senders) >= 4 and len(jb) >= 6:
        sev = min(1.0, 0.3 + 0.1 * len(senders))
        hits.append(ScenarioHit(
            code="SC-01", name="Cash structuring (just-below-threshold)", name_uz="Pulyani hisobot chegarasidan pastga bo'lib yuborish",
            matched=True, severity=sev,
            detail=f"{len(jb)} deposits in [{round(0.85 * T / 1e6)}–{round(T / 1e6)}] mln UZS from {len(senders)} distinct senders",
            evidence=[t.id for t in jb[:12]],
        ))
    else:
        hits.append(ScenarioHit(code="SC-01", name="Cash structuring (just-below-threshold)",
                                name_uz="Pulyani hisobot chegarasidan pastga bo'lib yuborish",
                                matched=False, detail="No threshold-proximity cluster found"))

    # SC-02 rapid pass-through
    drains = []
    for t in ins:
        start = dts[t.id]
        out_val = sum(o.amount for o in outs if dts[o.id] >= start and (dts[o.id] - start).total_seconds() <= 24 * 3600)
        if t.amount > 0 and out_val >= 0.7 * t.amount:
            drains.append(t.id)
    if len(drains) >= 3:
        hits.append(ScenarioHit(
            code="SC-02", name="Rapid pass-through (<24h)", name_uz="Tez o'tkazib yuborish",
            matched=True, severity=min(1.0, 0.35 + 0.08 * len(drains)),
            detail=f"{len(drains)} inflows of which ≥70% left the account within 24h",
            evidence=drains[:12],
        ))
    else:
        hits.append(ScenarioHit(code="SC-02", name="Rapid pass-through (<24h)",
                                name_uz="Tez o'tkazib yuborish", matched=False,
                                detail=f"Only {len(drains)} qualifying inflows (need ≥3)"))

    # SC-03 mule fan-in
    person_in_count = len({cp(t) for t in ins if t.from_kind == "person"})
    if person_in_count >= 8 and case.account_age_days <= 90:
        hits.append(ScenarioHit(
            code="SC-03", name="Mule fan-in on a young account", name_uz="Pul yutuvchi hisobga ko'p kirim",
            matched=True, severity=min(1.0, 0.4 + 0.04 * person_in_count),
            detail=f"{person_in_count} distinct person senders, account age {case.account_age_days}d ≤ 90d",
            evidence=[t.id for t in ins][:12],
        ))
    else:
        hits.append(ScenarioHit(code="SC-03", name="Mule fan-in on a young account",
                                name_uz="Pul yutuvchi hisobga ko'p kirim", matched=False,
                                detail=f"person senders={person_in_count} (need ≥8), age={case.account_age_days}d"))

    # SC-04 crypto off-ramp
    crypto_txs = [t for t in txs if "crypto" in memo_hits(t.memo)]
    uniq_in = len({cp(t) for t in ins})
    if crypto_txs and uniq_in >= 4 and total_in > 0:
        outs_crypto = [t for t in outs if "crypto" in memo_hits(t.memo)]
        if not outs_crypto and total_out / total_in < 0.5:
            matched = False
            detail = "Crypto memos present but no consolidated payout yet"
            ev: list[str] = []
        else:
            matched = True
            detail = f"crypto-related memos on {len(crypto_txs)} txs, {uniq_in} inbound counterparties"
            ev = [t.id for t in crypto_txs[:12]]
        hits.append(ScenarioHit(code="SC-04", name="Crypto off-ramp pattern", name_uz="Kripto-valyutaga chiqarish",
                                matched=matched, severity=0.85 if matched else 0.3, detail=detail, evidence=ev))
    else:
        hits.append(ScenarioHit(code="SC-04", name="Crypto off-ramp pattern", name_uz="Kripto-valyutaga chiqarish",
                                matched=False, detail="No crypto memos with inbound fan-in"))

    # SC-05 counterparty cycles
    neigh = _subject_cp_names(case)
    adj: dict[str, set[str]] = defaultdict(set)
    edge_map: dict[tuple[str, str], str] = {}
    for t in txs:
        a, b = t.from_name.strip().lower(), t.to_name.strip().lower()
        if a and b and a != b and a != "subj" and b != "subj" and a in neigh and b in neigh:
            key = (a, b) if a < b else (b, a)
            edge_map.setdefault(key, t.id)
            adj[a].add(b)
            adj[b].add(a)
    tri_edges: list[str] = []
    seen_tri: set[tuple[str, str, str]] = set()
    for a in adj:
        for b in adj[a]:
            if b <= a:
                continue
            for w in adj[a] & adj[b]:
                tri = (a, b, w) if a < b < w else tuple(sorted((a, b, w)))  # type: ignore[assignment]
                if tri in seen_tri:
                    continue
                seen_tri.add(tri)  # type: ignore[arg-type]
                tri_edges.extend(
                    e for e in (
                        edge_map.get((a, b) if a < b else (b, a)),
                        edge_map.get((a, w) if a < w else (w, a)),
                        edge_map.get((b, w) if b < w else (w, b)),
                    ) if e
                )
    if tri_edges:
        hits.append(ScenarioHit(
            code="SC-05", name="Counterparty cycle (triangle)", name_uz="Qarama-qarshi to'lov aylanasi",
            matched=True, severity=0.8, detail=f"{len(adj)} counterparties form closed loops among themselves",
            evidence=list(dict.fromkeys(tri_edges))[:12],
        ))
    else:
        hits.append(ScenarioHit(code="SC-05", name="Counterparty cycle (triangle)",
                                name_uz="Qarama-qarshi to'lov aylanasi", matched=False,
                                detail="No counterparty-to-counterparty edges"))

    # SC-06 turnover mismatch
    turnover = case.declared_turnover_monthly
    ratio = total_in / max(turnover * 3, 1.0)
    if turnover > 0 and ratio >= 4.0:
        hits.append(ScenarioHit(
            code="SC-06", name="Inflow vs declared turnover mismatch", name_uz="Omonat va deklaratsiya qilingan aylanma mos kelmasligi",
            matched=True, severity=min(1.0, 0.3 + 0.1 * (ratio - 4)),
            detail=f"90-day inflow {total_in / 1e6:.0f} mln UZS vs declared {turnover * 3 / 1e6:.0f} mln (×{ratio:.1f})",
            evidence=[t.id for t in sorted(ins, key=lambda x: -x.amount)[:8]],
        ))
    else:
        hits.append(ScenarioHit(code="SC-06", name="Inflow vs declared turnover mismatch",
                                name_uz="Omonat va deklaratsiya qilingan aylanma mos kelmasligi",
                                matched=False, detail=f"ratio ×{ratio:.1f} (need ≥4.0)"))

    return hits
