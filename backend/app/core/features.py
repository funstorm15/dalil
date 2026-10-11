"""Feature extraction over a normalized case.

Every feature is a plain float with a stable name (FEATURE_KEYS) — the order
is the model contract. Features are chosen so each one has an analyst-readable
meaning, which is what makes the score explainable ("top contributing
features" in the UI map 1:1 to these names).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from .normalize import memo_hits, names_match, norm_name, norm_phone, parse_ts, round_amount
from .schemas import CaseRecord, Transaction

REPORTING_THRESHOLD = 50_000_000  # UZS, cash-operations reporting threshold


def build_entity_clusters(case: CaseRecord) -> dict[str, str]:
    """Resolve counterparty identity across spelling variants.

    Same person can appear as "Testveks Kazlum", "testveks kazlum", "T. Kazlum"
    (Latin/Cyrillic mixed in UZ/RU data) or under two accounts sharing one
    phone. Union-find over: account, normalized name, phone.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    nodes: dict[str, tuple[str, str, str]] = {}  # key -> (name, phone, kind)
    for t in case.transactions:
        sides = []
        if t.direction == "in":
            sides.append((t.from_account, t.from_name, t.phone if t.from_kind != "subject" else "", t.from_kind))
        else:
            sides.append((t.to_account, t.to_name, t.phone if t.to_kind != "subject" else "", t.to_kind))
        for acct, name, phone, kind in sides:
            if kind == "subject" or not name or name == "SUBJ":
                continue
            key = acct or ("nm:" + norm_name(name))
            nodes.setdefault(key, (name, norm_phone(phone), kind))
            find(key)

    keys = list(nodes)
    tokens = {k: norm_name(nodes[k][0]).split() for k in keys}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            na, pa, _ = nodes[a]
            nb, pb, _ = nodes[b]
            same = (pa and pb and pa == pb) or name_merge_ok(
                na, nb, a, b, tokens)
            if same:
                union(a, b)

    clusters: dict[str, str] = {}
    members: dict[str, list[str]] = {}
    for k in keys:
        r = find(k)
        members.setdefault(r, []).append(k)
    # stable cluster ids: c1, c2, ...
    for idx, (_root, mem) in enumerate(sorted(members.items(), key=lambda x: min(x[1])), start=1):
        cid = f"c{idx}"
        for m in mem:
            clusters[m] = cid
    return clusters

def name_merge_ok(na: str, nb: str, key_a: str, key_b: str,
                  tokens: dict[str, list[str]]) -> bool:
    """Nameship decision with an ambiguity guard for abbreviated names.

    Full names merge like normalize.names_match (transliteration / subset /
    similarity). An abbreviated name ("T. Kazlum") merges only when its
    initial resolves to exactly one distinct person-name in this case among
    nodes sharing a non-initial token — if both "Testveks Kazlum" and
    "Testvekslong Kazlum" are present, nothing merges with "T. Kazlum".
    Candidates are counted by distinct normalized name, so spelling variants
    of one person do not create false ambiguity.
    """
    if na == nb:
        return True
    ta, tb = tokens[key_a], tokens[key_b]
    init_a = [t for t in ta if len(t) == 1]
    init_b = [t for t in tb if len(t) == 1]
    if not init_a and not init_b:
        return names_match(na, nb)

    def shares_long(x: list[str], y: list[str]) -> bool:
        lx = [t for t in x if len(t) > 1]
        ly = [t for t in y if len(t) > 1]
        if not lx or not ly:
            return True  # one side is initials-only
        return bool(set(lx) & set(ly))

    # ambiguity guard: each abbreviated side must resolve to exactly one
    # distinct normalized name among the OTHER nodes of this case
    for init, side, skip in ((init_a, ta, key_a), (init_b, tb, key_b)):
        if not init:
            continue
        cands: set[str] = set()
        for k, toks in tokens.items():
            if k == skip:
                continue
            if all(any(w.startswith(i) and len(w) > 1 for w in toks) for i in init) \
                    and shares_long(side, toks):
                cands.add(" ".join(sorted(toks)))
        if len(cands) != 1:
            return False

    long_a = [t for t in ta if len(t) > 1]
    long_b = [t for t in tb if len(t) > 1]
    if init_a and not init_b:
        return (all(any(w.startswith(i) and len(w) > 1 for w in tb) for i in init_a)
                and set(long_a) <= set(long_b))
    if init_b and not init_a:
        return (all(any(w.startswith(i) and len(w) > 1 for w in ta) for i in init_b)
                and set(long_b) <= set(long_a))
    return sorted(init_a) == sorted(init_b) and shares_long(ta, tb)


FEATURE_KEYS: list[str] = [
    # volume / shape
    "n_tx", "n_in", "n_out", "total_in", "total_out", "net_flow",
    "avg_in", "avg_out", "max_in", "max_out", "median_amount",
    # threshold proximity (structuring)
    "n_in_just_below", "share_in_just_below", "senders_just_below",
    "n_in_mid_band", "share_round",
    # timing / velocity
    "span_days", "tx_per_day", "night_share", "drain_24h_share",
    "in_out_lag_med_h",
    # counterparties / graph
    "uniq_in", "uniq_out", "uniq_total", "fan_in_ratio", "hhi_in",
    "share_person_in", "uniq_person_in", "smurf_phone_clusters",
    "neighbor_edges", "triangles",
    # channels
    "share_cash", "share_p2p", "share_wire", "share_pos_card",
    # memos
    "memo_empty_share", "memo_vague_hits", "memo_crypto_hits",
    "memo_salary_hits", "memo_trade_hits", "memo_gambling_hits",
    # subject / context
    "account_age_days", "declared_turnover_monthly", "volume_vs_turnover",
    "is_business",
    # balance behaviour
    "end_balance", "min_day_balance", "days_near_zero_share",
    "retention_ratio",
]

N_FEATURES = len(FEATURE_KEYS)


def _counterparty(tx: Transaction, subject_acct: str) -> tuple[str, str, str]:
    """Return (key, display_name, kind) of the non-subject side."""
    if tx.direction == "in":
        return tx.from_account or tx.from_name, tx.from_name, tx.from_kind
    return tx.to_account or tx.to_name, tx.to_name, tx.to_kind


def _counterparty_cluster(tx: Transaction, clusters: dict[str, str]) -> tuple[str, str, str]:
    key, name, kind = _counterparty(tx, "")
    if kind == "subject":
        return key, name, kind
    return clusters.get(key, key), name, kind


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 else (s[m - 1] + s[m]) / 2


def extract_features(case: CaseRecord, fill: dict[str, float] | None = None) -> dict[str, float]:
    txs = case.transactions
    subj = case.subject_account
    clusters = build_entity_clusters(case)
    f: dict[str, float] = {k: 0.0 for k in FEATURE_KEYS}
    if not txs:
        return f

    dts: list[datetime] = []
    for t in txs:
        d = parse_ts(t.ts)
        dts.append(d or datetime(2026, 1, 1))

    amounts = [t.amount for t in txs]
    ins = [(t, d) for t, d in zip(txs, dts, strict=False) if t.direction == "in"]
    outs = [(t, d) for t, d in zip(txs, dts, strict=False) if t.direction == "out"]
    total_in = sum(t.amount for t, _ in ins)
    total_out = sum(t.amount for t, _ in outs)

    f["n_tx"] = float(len(txs))
    f["n_in"] = float(len(ins))
    f["n_out"] = float(len(outs))
    f["total_in"] = total_in
    f["total_out"] = total_out
    f["net_flow"] = total_in - total_out
    f["avg_in"] = total_in / len(ins) if ins else 0.0
    f["avg_out"] = total_out / len(outs) if outs else 0.0
    f["max_in"] = max((t.amount for t, _ in ins), default=0.0)
    f["max_out"] = max((t.amount for t, _ in outs), default=0.0)
    f["median_amount"] = _median(amounts)

    # --- structuring proximity
    T = REPORTING_THRESHOLD
    just_below = [(t, d) for t, d in ins if 0.85 * T <= t.amount < T]
    mid_band = [(t, d) for t, d in ins if 0.5 * T <= t.amount < 0.85 * T]
    f["n_in_just_below"] = float(len(just_below))
    f["share_in_just_below"] = len(just_below) / len(ins) if ins else 0.0
    f["senders_just_below"] = float(len({_counterparty(t, subj)[0] for t, _ in just_below}))
    f["n_in_mid_band"] = float(len(mid_band))
    f["share_round"] = sum(1 for a in amounts if round_amount(a)) / len(amounts)

    # --- timing
    max((dts[i + 1] - dts[i]).total_seconds() for i in range(len(dts) - 1)) / 86400 if len(dts) > 1 else 0.0
    span_days = (max(dts) - min(dts)).total_seconds() / 86400 or 1.0
    f["span_days"] = span_days
    f["tx_per_day"] = len(txs) / max(span_days, 1.0)
    f["night_share"] = sum(1 for d in dts if 0 <= d.hour < 6) / len(dts)

    # drain: money in, gone again within 24h (pass-through)
    drain_hits = 0
    for _i, (t, d) in enumerate(ins):
        if t.amount <= 0:
            continue
        out_val = 0.0
        for t2, d2 in outs:
            if d2 >= d and (d2 - d).total_seconds() <= 24 * 3600:
                out_val += t2.amount
                if out_val >= 0.7 * t.amount:
                    drain_hits += 1
                    break
    f["drain_24h_share"] = drain_hits / len(ins) if ins else 0.0

    # lag from in to the next out
    lags = []
    oi = 0
    for _t, d in ins:
        while oi < len(outs) and outs[oi][1] < d:
            oi += 1
        if oi < len(outs):
            lags.append((outs[oi][1] - d).total_seconds() / 3600)
    f["in_out_lag_med_h"] = _median([max(lag, 0.0) for lag in lags])

    # --- counterparties (identity-resolved)
    cp_in: dict[str, float] = defaultdict(float)
    person_in: set[str] = set()
    phones: dict[str, set[str]] = defaultdict(set)
    for t, _ in ins:
        key, _name, kind = _counterparty_cluster(t, clusters)
        cp_in[key] += t.amount
        if kind == "person":
            person_in.add(key)
        if t.phone:
            phones[t.phone].add(key)
    cp_out: set[str] = set()
    for t, _ in outs:
        key, _name, kind = _counterparty_cluster(t, clusters)
        if kind != "subject":
            cp_out.add(key)
    f["uniq_in"] = float(len(cp_in))
    f["uniq_out"] = float(len(cp_out))
    f["uniq_total"] = float(len(set(cp_in) | cp_out))
    f["fan_in_ratio"] = len(cp_in) / len(ins) if ins else 0.0
    if total_in > 0:
        f["hhi_in"] = sum((v / total_in) ** 2 for v in cp_in.values())
    f["uniq_person_in"] = float(len(person_in))
    f["share_person_in"] = len(person_in) / len(cp_in) if cp_in else 0.0
    f["smurf_phone_clusters"] = float(sum(1 for v in phones.values() if len(v) > 1))

    # graph among counterparties (both sides of a tx are known counterparties)
    neighbor_keys = set(cp_in) | cp_out
    adj: set[tuple[str, str]] = set()
    for t in txs:
        a_key = clusters.get(t.from_account or t.from_name, t.from_account or t.from_name)
        b_key = clusters.get(t.to_account or t.to_name, t.to_account or t.to_name)
        if t.from_kind != "subject" and t.to_kind != "subject" and a_key != b_key \
                and a_key in neighbor_keys and b_key in neighbor_keys:
            adj.add((a_key, b_key) if a_key < b_key else (b_key, a_key))
    f["neighbor_edges"] = float(len(adj))
    # triangles: for each edge (u,v), common neighbor w in neighbor set
    node_adj: dict[str, set[str]] = defaultdict(set)
    for u, v in adj:
        node_adj[u].add(v)
        node_adj[v].add(u)
    tris = set()
    for u, v in adj:
        for w in node_adj[u] & node_adj[v]:
            tris.add(tuple(sorted((u, v, w))))
    f["triangles"] = float(len(tris))

    # --- channels
    n = len(txs)
    cash = sum(1 for t in txs if t.channel in {"cash_in", "cash_out", "atm"})
    f["share_cash"] = cash / n
    f["share_p2p"] = sum(1 for t in txs if t.channel == "p2p") / n
    f["share_wire"] = sum(1 for t in txs if t.channel == "wire") / n
    f["share_pos_card"] = sum(1 for t in txs if t.channel in {"card", "pos", "merchant"}) / n

    # --- memos
    memos = [t.memo.strip() for t in txs]
    nonempty = [m for m in memos if m]
    f["memo_empty_share"] = (len(memos) - len(nonempty)) / n
    hits = Counter(h for m in nonempty for h in memo_hits(m))
    f["memo_vague_hits"] = float(hits.get("vague", 0))
    f["memo_crypto_hits"] = float(hits.get("crypto", 0))
    f["memo_salary_hits"] = float(hits.get("salary", 0))
    f["memo_trade_hits"] = float(hits.get("trade_goods", 0))
    f["memo_gambling_hits"] = float(hits.get("gambling", 0))

    # --- subject context
    # subject metadata: missing values are filled ONLY from an explicit `fill`
    # map (the pipeline passes training medians and reports the imputation)
    fill = fill or {}
    age = case.account_age_days if case.account_age_days is not None else fill.get("account_age_days")
    turnover = (case.declared_turnover_monthly if case.declared_turnover_monthly is not None
                else fill.get("declared_turnover_monthly"))
    if age is None or turnover is None:
        raise ValueError("subject metadata missing and no explicit imputation supplied")
    f["account_age_days"] = float(age)
    f["declared_turnover_monthly"] = float(turnover)
    f["volume_vs_turnover"] = total_in / max(float(turnover) * 3, 1.0)
    f["is_business"] = 1.0 if case.subject_kind == "business" else 0.0

    # --- balance behaviour
    day_bal: dict[str, float] = defaultdict(float)
    day_in: dict[str, float] = defaultdict(float)
    for t, d in zip(txs, dts, strict=False):
        key = d.strftime("%Y-%m-%d")
        day_bal[key] += t.amount if t.direction == "in" else -t.amount
        if t.direction == "in":
            day_in[key] += t.amount
    bal = 0.0
    mins: list[float] = []
    ends: list[float] = []
    near_zero = 0
    for key in sorted(day_bal):
        bal += day_bal[key]
        mins.append(bal)
        ends.append(bal)
        if bal <= 0.1 * max(day_in.get(key, 0.0), 1_000_000) and day_in.get(key, 0) > 0:
            near_zero += 1
    f["end_balance"] = ends[-1] if ends else 0.0
    f["min_day_balance"] = min(mins) if mins else 0.0
    f["days_near_zero_share"] = near_zero / len(ends) if ends else 0.0
    f["retention_ratio"] = max(0.0, (total_in - total_out)) / total_in if total_in > 0 else 0.0

    # safety: no NaN/inf
    for k, v in f.items():
        if v != v or v in (float("inf"), float("-inf")):
            f[k] = 0.0
    return f


def vector(features: dict[str, float]) -> list[float]:
    return [float(features.get(k, 0.0)) for k in FEATURE_KEYS]
