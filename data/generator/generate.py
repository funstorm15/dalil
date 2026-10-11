"""Synthetic AML casebook generator for DALIL.

Generates alert cases (subject account + 90-day transaction window) with
injected AML typologies and clean controls, across train / test / novel
(held-out variants) / demo splits. Everything is synthetic: names, accounts,
phones, amounts are fabricated with a fixed seed and carry no real personal
data. See data/generated/DATA_CARD.md for the licence and parameters.

Usage:
    python data/generator/generate.py --out data/generated --seed 20261010
"""
from __future__ import annotations

import argparse
import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

WINDOW_DAYS = 90
END_TS = datetime(2026, 6, 30, 21, 0, 0)

# Cash-reporting threshold used by the scenario rules (UZS). Overridden from
# the config file the team documents in DATA_CARD.md.
REPORTING_THRESHOLD = 50_000_000

FIRST_NAMES = [f"P{i:03d}" for i in range(40)]
LAST_NAMES = [f"N{i:03d}" for i in range(30)]
BUSINESS_WORDS = [f"DEMO Company C{i:03d}" for i in range(19)]
BUSINESS_FORMS = ["MChJ", "MChJ", "MChJ", "MKK"]
CITIES = [
    "Toshkent", "Samarqand", "Andijon", "Namangan", "Farg'ona", "Buxoro",
    "Xiva", "Nukus", "Jizzax", "Qarshi", "Termiz", "Guliston",
]
RUS_CITIES = ["Ташкент", "Самарканд", "Фергана", "Бухара", "Наманган"]
GEO = CITIES + RUS_CITIES

STREETS = [f"DEMO Street S{i:03d}" for i in range(6)]

MEMOS_CLEAN = [
    "uy-joy ijara", "kommunal", "demo savdo", "apteka", "benzin", "metro",
    "kofe", "sotib oldim", "oziq-ovqat", "мобильный", "интернет", "коммуналка",
    "demo kafé", "taxi", "dori-darmon", "bolalar bog'cha", "sug'urta",
]
MEMOS_SUSPICIOUS = [
    "qarz qaytarish", "avans", "товар", "perevod", "kunlik hisob", "",
    "????", "usdt otdam", "xizmat haqi", "oldindan to'lov", "перевод за товар",
]


def acct(rng: random.Random) -> str:
    return "DEMO-ACCOUNT-" + "".join(rng.choices(string.ascii_uppercase, k=24))


def phone(rng: random.Random) -> str:
    return "DEMO-PHONE-" + "".join(rng.choices(string.ascii_uppercase, k=8))


def person_name(rng: random.Random) -> str:
    return f"DEMO Person {rng.choice(FIRST_NAMES)}-{rng.choice(LAST_NAMES)}"


def business_name(rng: random.Random) -> str:
    return f"{rng.choice(BUSINESS_WORDS)} {rng.choice(BUSINESS_FORMS)}"


def messy_amount(rng: random.Random, value: float):
    """30% of amounts come back as messy strings — the pipeline must cope."""
    if rng.random() > 0.3:
        return value
    style = rng.choice(["space", "dots", "comma_mln", "int"])
    if style == "space":
        return f"{int(value):,}".replace(",", " ")
    if style == "dots":
        return f"{int(value):,}".replace(",", ".")
    if style == "comma_mln":
        return f"{value / 1_000_000:.1f}".replace(".", ",") + " млн"
    return int(value)


def messy_ts(rng: random.Random, ts: datetime):
    if rng.random() > 0.3:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return rng.choice([
        ts.strftime("%d.%m.%Y %H:%M"),
        ts.strftime("%Y-%m-%dT%H:%M:%S"),
        ts.strftime("%d/%m/%Y %H:%M"),
    ])


def tx(
    rng: random.Random,
    n: int,
    case_id: str,
    ts: datetime,
    amount: float,
    direction: str,
    other_name: str,
    other_kind: str,
    channel: str,
    memo: str,
    other_phone: str = "",
    other_geo: str = "",
) -> dict:
    s_acct_holder = "SUBJ"
    other_acct = acct(rng)
    if direction == "in":
        frm = dict(name=other_name, kind=other_kind, account=other_acct, phone=other_phone, geo=other_geo)
        to = dict(name=s_acct_holder, kind="subject", account="SUBJ", phone="", geo="")
    else:
        frm = dict(name=s_acct_holder, kind="subject", account="SUBJ", phone="", geo="")
        to = dict(name=other_name, kind=other_kind, account=other_acct, phone=other_phone, geo=other_geo)
    return {
        "id": f"{case_id}-T{n:04d}",
        "ts": messy_ts(rng, ts),
        "amount": messy_amount(rng, amount),
        "direction": direction,
        "from_account": frm["account"],
        "from_name": frm["name"],
        "from_kind": frm["kind"],
        "to_account": to["account"],
        "to_name": to["name"],
        "to_kind": to["kind"],
        "channel": channel,
        "memo": memo,
        "phone": frm["phone"] or to["phone"],
        "geo": frm["geo"] or to["geo"],
    }


class CaseBuilder:
    def __init__(self, rng: random.Random, case_id: str, label: str, variant: str):
        self.rng = rng
        self.case_id = case_id
        self.label = label
        self.variant = variant  # base | novel
        self.txs: list[dict] = []
        self.n = 0
        self.sum_in = 0.0
        self.subject_kind = "person"
        self.age_days = 400
        self.turnover_override: float | None = None

    def add(self, *a, **kw) -> None:
        self.n += 1
        if len(a) > 2 and a[2] == "in":
            self.sum_in += float(a[1])
        self.txs.append(tx(self.rng, self.n, self.case_id, *a, **kw))

    def background_person(self) -> None:
        rng = self.rng
        start = END_TS - timedelta(days=WINDOW_DAYS)
        # salary in, monthly
        for m in range(3):
            self.add(start + timedelta(days=7 + m * 30, hours=rng.randint(8, 12)),
                     rng.randint(7, 14) * 1_000_000, "in", person_name(rng), "person",
                     "wire", "maosh", other_geo=rng.choice(CITIES))
        # daily life spending
        for _ in range(rng.randint(18, 40)):
            self.add(start + timedelta(days=rng.randint(0, WINDOW_DAYS), hours=rng.randint(8, 22)),
                     rng.choice([1, 2, 3, 5, 7, 12, 20, 35, 60]) * 100_000 * rng.choice([1, 1, 1, 1.5]),
                     "out", rng.choice(BUSINESS_WORDS) + " MChJ", "business",
                     rng.choice(["card", "pos", "p2p"]),
                     "" if rng.random() < 0.12 else rng.choice(MEMOS_CLEAN))
        # occasional large legitimate movements (property, car, family, credit)
        if rng.random() < 0.5:
            self.add(start + timedelta(days=rng.randint(0, WINDOW_DAYS), hours=rng.randint(9, 18)),
                     rng.randint(30, 600) * 1_000_000, "in",
                     person_name(rng) if rng.random() < 0.6 else business_name(rng),
                     "person" if rng.random() < 0.6 else "business",
                     "wire", rng.choice(["kredit tushumi", "biznes daromad", "uy sotildi", "depozit qaytarish"]),
                     other_geo=rng.choice(CITIES))
        if rng.random() < 0.6:
            self.add(start + timedelta(days=rng.randint(0, WINDOW_DAYS), hours=rng.randint(9, 19)),
                     rng.randint(20, 450) * 1_000_000, "out",
                     rng.choice([business_name(rng), person_name(rng), "DEMO Company BANK"]),
                     "business" if rng.random() < 0.7 else "person",
                     rng.choice(["wire", "p2p", "pos"]),
                     rng.choice(["uy-joy to'lovi", "avtomobil", "kredit qaytarish", "oilaga", ""]),
                     other_geo=rng.choice(CITIES))

    def background_business(self) -> None:
        rng = self.rng
        start = END_TS - timedelta(days=WINDOW_DAYS)
        for _ in range(rng.randint(6, 14)):  # customer receipts
            self.add(start + timedelta(days=rng.randint(0, WINDOW_DAYS), hours=rng.randint(9, 19)),
                     rng.randint(2, 45) * 1_000_000, "in", person_name(rng), "person",
                     rng.choice(["p2p", "pos", "merchant"]), rng.choice(MEMOS_CLEAN))
        for _ in range(rng.randint(5, 14)):  # supplier / payroll style outs
            self.add(start + timedelta(days=rng.randint(0, WINDOW_DAYS), hours=rng.randint(9, 18)),
                     rng.randint(3, 150) * 1_000_000, "out", business_name(rng), "business",
                     rng.choice(["wire", "p2p"]),
                     "" if rng.random() < 0.10 else "tovar uchun")
        if rng.random() < 0.7:  # taxes / utilities
            for _ in range(rng.randint(1, 3)):
                self.add(start + timedelta(days=rng.randint(0, WINDOW_DAYS), hours=rng.randint(9, 17)),
                         rng.randint(5, 60) * 1_000_000, "out", "DEMO Company TAX", "business",
                         "wire", "soliq to'lovi")
        if rng.random() < 0.4:  # one big legit receipt or payment
            self.add(start + timedelta(days=rng.randint(0, WINDOW_DAYS), hours=rng.randint(9, 18)),
                     rng.randint(80, 500) * 1_000_000,
                     rng.choice(["in", "out"]), person_name(rng), "person",
                     "wire", rng.choice(["investitsiya", "kredit", ""]),
                     other_geo=rng.choice(CITIES))

    # ---- typologies -----------------------------------------------------
    def structuring(self) -> None:
        rng, T = self.rng, REPORTING_THRESHOLD
        n_senders = rng.randint(3, 12) if self.variant == "base" else rng.randint(2, 3)
        lo = 0.86 if self.variant == "base" else 0.68
        window = timedelta(days=rng.choice([10, 20, 40, 60, 75]))
        t0 = END_TS - timedelta(days=WINDOW_DAYS - 5) - window
        senders = [(person_name(rng), phone(rng), rng.choice(CITIES)) for _ in range(n_senders)]
        shared_phone = rng.random() < 0.4  # some smurfs share one phone
        n_ops = rng.randint(5, 22)
        for i in range(n_ops):
            nm, ph, geo = senders[i % len(senders)]
            if shared_phone:
                ph = senders[0][1]
            ts = t0 + timedelta(days=rng.randint(0, window.days), hours=rng.randint(8, 21),
                                minutes=rng.randint(0, 59))
            amt = rng.uniform(lo, 0.995) * T
            amt = round(amt / 100_000) * 100_000
            self.add(ts, amt, "in", nm, "person", rng.choice(["cash_in", "p2p", "p2p"]),
                     rng.choice(MEMOS_SUSPICIOUS), other_phone=ph, other_geo=geo)
        # most money leaves soon after
        out_ts = END_TS - timedelta(days=rng.randint(1, 10))
        self.add(out_ts, rng.uniform(0.5, 0.85) * self.total_in() or 40_000_000, "out",
                 business_name(rng), "business", "wire", "hisobot")

    def pass_through(self) -> None:
        rng = self.rng
        n = rng.randint(1, 7) if self.variant == "base" else rng.randint(1, 3)
        for _i in range(n):
            ts_in = END_TS - timedelta(days=rng.randint(5, WINDOW_DAYS - 5), hours=rng.randint(0, 20))
            amt = rng.randint(30, 400) * 1_000_000
            self.add(ts_in, amt, "in", business_name(rng) if rng.random() < 0.5 else person_name(rng),
                     "business" if rng.random() < 0.5 else "person",
                     rng.choice(["wire", "p2p", "p2p"]), rng.choice(["tovar", "oldindan to'lov", "qarz"]),
                     other_geo=rng.choice(CITIES))
            delay_h = rng.uniform(0.5, 30) if self.variant == "base" else rng.uniform(72, 120)
            self.add(ts_in + timedelta(hours=delay_h), amt * rng.uniform(0.9, 0.99), "out",
                     person_name(rng), "person",
                     rng.choice(["p2p", "cash_out", "atm"] if self.variant == "novel" else ["p2p", "cash_out"]),
                     rng.choice(MEMOS_SUSPICIOUS), other_geo=rng.choice(GEO))

    def mule_fanin(self) -> None:
        rng = self.rng
        n_senders = rng.randint(6, 25) if self.variant == "base" else rng.randint(4, 7)
        for _i in range(n_senders):
            ts = END_TS - timedelta(days=rng.randint(1, WINDOW_DAYS), hours=rng.randint(7, 23))
            amt = rng.randint(3, 60) * 1_000_000
            self.add(ts, amt, "in", person_name(rng), "person",
                     rng.choice(["p2p", "p2p", "cash_in"]), rng.choice(MEMOS_SUSPICIOUS),
                     other_phone=phone(rng), other_geo=rng.choice(CITIES))
        # consolidate to 1-2 accounts, often cash
        for _ in range(rng.randint(1, 2)):
            ts = END_TS - timedelta(days=rng.randint(0, 5))
            self.add(ts, self.total_in() * rng.uniform(0.6, 0.95), "out",
                     person_name(rng), "person", rng.choice(["cash_out", "atm", "wire"]), "")

    def crypto_offramp(self) -> None:
        rng = self.rng
        for _i in range(rng.randint(3, 14)):
            ts = END_TS - timedelta(days=rng.randint(1, WINDOW_DAYS), hours=rng.randint(8, 23))
            self.add(ts, rng.randint(5, 120) * 1_000_000, "in", person_name(rng), "person",
                     "p2p", rng.choice(["usdt", "p2p buy", "tether", "", "perevod"]),
                     other_phone=phone(rng), other_geo=rng.choice(GEO))
        self.add(END_TS - timedelta(days=rng.randint(0, 6)),
                 self.total_in() * rng.uniform(0.7, 0.98), "out", "DEMO Company CRYPTO",
                 "business", "p2p", "usdt")
        self.add(END_TS - timedelta(days=rng.randint(0, 4)),
                 self.total_in() * rng.uniform(0.05, 0.15), "out",
                 person_name(rng), "person", "cash_out", "")

    def cycle_layering(self) -> None:
        rng = self.rng
        c1_name, c2_name = person_name(rng), person_name(rng)
        c1, c2 = phone(rng), phone(rng)
        t0 = END_TS - timedelta(days=rng.randint(20, 60))
        amt1 = rng.randint(80, 300) * 1_000_000
        self.add(t0, amt1, "in", c1_name, "person", "p2p", "qarz", other_phone=c1, other_geo=rng.choice(CITIES))
        self.add(t0 + timedelta(hours=rng.uniform(1, 30)), amt1 * 0.97, "out", c2_name, "person",
                 "p2p", "qarz", other_phone=c2, other_geo=rng.choice(CITIES))
        self.add(t0 + timedelta(hours=rng.uniform(30, 72)), amt1 * 0.95, "in", c2_name, "person",
                 "p2p", "qaytarish", other_phone=c2, other_geo=rng.choice(CITIES))
        # c1 -> c2 direct edge closes the triangle
        self.add(t0 + timedelta(hours=rng.uniform(1, 50)), rng.randint(20, 90) * 1_000_000,
                 "out", c1_name, "person", "p2p", "xizmat haqi", other_phone=c1,
                 other_geo=rng.choice(CITIES))
        # extra ring members for the novel variant
        if self.variant == "novel":
            c3_name = person_name(rng)
            c3 = phone(rng)
            self.add(t0 + timedelta(hours=5), rng.randint(50, 150) * 1_000_000, "out",
                     c3_name, "person", "wire", "", other_phone=c3)
            self.add(t0 + timedelta(hours=40), rng.randint(50, 150) * 1_000_000, "in",
                     c3_name, "person", "wire", "", other_phone=c3)

    def total_in(self) -> float:
        return self.sum_in or 1.0

    def finish(self, rng: random.Random, age_days: int, turnover: float) -> dict:
        self.txs.sort(key=lambda t: str(t["ts"]))
        return {
            "case_id": self.case_id,
            "subject_account": acct(rng),
            "subject_name": business_name(rng) if self.subject_kind == "business" else person_name(rng),
            "subject_kind": self.subject_kind,
            "account_age_days": age_days,
            "declared_turnover_monthly": turnover,
            "branch": rng.choice(CITIES),
            "alert_source": "scenario-engine",
            "opened_at": (END_TS + timedelta(days=rng.randint(1, 5))).strftime("%Y-%m-%d"),
            "transactions": self.txs,
            "labels": [self.label] if self.label != "clean" else ["clean"],
            "is_suspicious": self.label != "clean",
            "split": "base",
            "generator_variant": self.variant,
        }


def gen_case(rng: random.Random, case_id: str, label: str, variant: str) -> dict:
    b = CaseBuilder(rng, case_id, label, variant)
    is_biz = label in ("structuring",) and rng.random() < 0.6
    b.subject_kind = "business" if is_biz else "person"
    if is_biz:
        b.background_business()
    else:
        b.background_person()

    if label == "structuring":
        b.age_days = rng.randint(90, 1200)
        b.structuring()
    elif label == "pass_through":
        b.age_days = rng.randint(60, 800)
        b.pass_through()
    elif label == "mule_fanin":
        b.subject_kind = "person"
        b.age_days = rng.randint(5, 180) if variant == "base" else rng.randint(120, 400)
        b.mule_fanin()
    elif label == "crypto_offramp":
        b.subject_kind = "person"
        b.age_days = rng.randint(30, 900)
        b.crypto_offramp()
    elif label == "cycle_layering":
        b.age_days = rng.randint(60, 1000)
        b.cycle_layering()
    else:  # clean — includes legitimate patterns that look suspicious
        b.age_days = rng.randint(15, 60) if rng.random() < 0.15 else rng.randint(100, 2500)
        roll = rng.random()
        if roll < 0.35:  # trade receipts grazing the threshold (repeat partners)
            for _ in range(rng.randint(2, 5)):
                ts = END_TS - timedelta(days=rng.randint(1, WINDOW_DAYS), hours=rng.randint(9, 18))
                b.add(ts, rng.uniform(0.7, 0.99) * REPORTING_THRESHOLD, "in",
                      person_name(rng), "person", "p2p", "tovar uchun")
        elif roll < 0.50:  # cash-intensive small trader: many senders, young-ish business
            b.subject_kind = "business"
            b.age_days = rng.randint(400, 1600)
            senders_ = [(person_name(rng), phone(rng)) for _ in range(rng.randint(6, 15))]
            for i in range(rng.randint(14, 40)):
                nm, ph = senders_[i % len(senders_)]
                ts = END_TS - timedelta(days=rng.randint(1, WINDOW_DAYS), hours=rng.randint(9, 21))
                b.add(ts, rng.randint(4, 40) * 1_000_000, "in", nm, "person",
                      rng.choice(["cash_in", "p2p", "pos"]), rng.choice(["xizmat haqi", "tovar", ""]),
                      other_phone=ph, other_geo=rng.choice(CITIES))
            for _ in range(rng.randint(4, 10)):
                ts = END_TS - timedelta(days=rng.randint(1, WINDOW_DAYS), hours=rng.randint(10, 19))
                b.add(ts, rng.randint(5, 60) * 1_000_000, "out", business_name(rng), "business",
                      "wire", "tovar")
        elif roll < 0.62:  # one-off asset sale: huge single inflow, low declared turnover
            ts = END_TS - timedelta(days=rng.randint(5, WINDOW_DAYS))
            b.add(ts, rng.randint(200, 700) * 1_000_000, "in", person_name(rng), "person",
                  "wire", "uy sotildi", other_geo=rng.choice(CITIES))
            for _ in range(rng.randint(2, 5)):
                ts2 = END_TS - timedelta(days=rng.randint(0, WINDOW_DAYS))
                b.add(ts2, rng.randint(20, 150) * 1_000_000, "out", business_name(rng),
                      "business", rng.choice(["wire", "p2p"]), "qurilish materiali")
        elif roll < 0.72:  # marketplace distributor: huge legit volume, many counterparties
            b.subject_kind = "business"
            b.age_days = rng.randint(400, 2000)
            senders_ = [(person_name(rng), phone(rng)) if rng.random() < 0.5
                        else (business_name(rng), "") for _ in range(rng.randint(10, 25))]
            for i in range(rng.randint(20, 50)):
                nm, ph = senders_[i % len(senders_)]
                ts = END_TS - timedelta(days=rng.randint(1, WINDOW_DAYS), hours=rng.randint(9, 20))
                b.add(ts, rng.randint(5, 130) * 1_000_000, "in", nm,
                      "person" if ph else "business",
                      rng.choice(["p2p", "wire", "pos", "merchant"]),
                      rng.choice(["tovar", "buyurtma", "hisob raqam", "xizmat", ""]),
                      other_phone=ph, other_geo=rng.choice(CITIES))
            for _ in range(rng.randint(15, 40)):
                ts = END_TS - timedelta(days=rng.randint(1, WINDOW_DAYS), hours=rng.randint(9, 19))
                b.add(ts, rng.randint(10, 300) * 1_000_000, "out", business_name(rng),
                      "business", rng.choice(["wire", "p2p"]), "tovar uchun")
            if rng.random() < 0.5:
                for _ in range(rng.randint(2, 6)):
                    ts = END_TS - timedelta(days=rng.randint(1, WINDOW_DAYS), hours=rng.randint(9, 21))
                    b.add(ts, rng.randint(3, 40) * 1_000_000, "in", person_name(rng), "person",
                          "cash_in", "", other_phone=phone(rng), other_geo=rng.choice(CITIES))
            b.turnover_override = None  # declared normally; volume will exceed it
        if rng.random() < 0.30:  # clean-but-busy: many small receipts
            for _ in range(rng.randint(8, 18)):
                ts = END_TS - timedelta(days=rng.randint(1, WINDOW_DAYS), hours=rng.randint(9, 20))
                b.add(ts, rng.randint(2, 20) * 1_000_000, "in", person_name(rng), "person",
                      "p2p", "xizmat haqi")

    turnover = rng.randint(30, 500) * 1_000_000 if b.subject_kind == "business" else rng.randint(8, 40) * 1_000_000
    if b.turnover_override is not None:
        turnover = b.turnover_override
    elif label != "clean" and b.sum_in > 0 and rng.random() < 0.30:
        # 30% of suspects have KYC declarations that match their real flow
        turnover = max(turnover, (b.sum_in / 3.0) * rng.uniform(0.7, 1.3))
    return b.finish(rng, b.age_days, turnover)


LABEL_MIX_TRAIN = [
    ("clean", 0.42),
    ("structuring", 0.16),
    ("pass_through", 0.14),
    ("mule_fanin", 0.13),
    ("crypto_offramp", 0.08),
    ("cycle_layering", 0.07),
]


def pick_label(rng: random.Random, mix=LABEL_MIX_TRAIN) -> str:
    r, acc = rng.random(), 0.0
    for label, p in mix:
        acc += p
        if r <= acc:
            return label
    return mix[-1][0]


def generate(out: Path, seed: int, n_train: int, n_test: int, n_novel: int, n_demo: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    def write(name: str, rows: list[dict]) -> None:
        with (out / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{name}: {len(rows)} cases")

    train = []
    for i in range(n_train):
        label = pick_label(rng)
        variant = "novel" if rng.random() < 0.15 else "base"  # a few variants leak into train
        row = gen_case(rng, f"TR-{i:05d}", label, variant)
        row["split"] = "train"
        train.append(row)

    test = []
    for i in range(n_test):
        row = gen_case(rng, f"TE-{i:05d}", pick_label(rng), "base")
        row["split"] = "test"
        test.append(row)

    novel = []
    for i in range(n_novel):
        label = pick_label(rng)
        row = gen_case(rng, f"NV-{i:05d}", "clean" if label == "clean" else label, "novel")
        row["split"] = "novel"
        row["generator_variant"] = "novel" if label != "clean" else "base"
        novel.append(row)

    demo = []
    for i in range(n_demo):
        row = gen_case(rng, f"DE-{i:05d}", pick_label(rng), "base")
        row["split"] = "demo"
        demo.append(row)

    write("cases_train.jsonl", train)
    write("cases_test.jsonl", test)
    write("cases_novel.jsonl", novel)
    write("cases_demo.jsonl", demo)

    counts: dict[str, int] = {}
    for rows in (train, test, novel, demo):
        for r in rows:
            for lab in r["labels"]:
                counts[lab] = counts.get(lab, 0) + 1
    card = {
        "name": "DALIL synthetic AML casebook",
        "generated_by": "data/generator/generate.py",
        "seed": seed,
        "reporting_threshold_uzs": REPORTING_THRESHOLD,
        "window_days": WINDOW_DAYS,
        "end_ts": END_TS.isoformat(),
        "splits": {
            "train": n_train, "test": n_test, "novel": n_novel, "demo": n_demo,
        },
        "label_counts": counts,
        "label_mix_train": {lab: prob for lab, prob in LABEL_MIX_TRAIN},
        "synthetic": True,
        "contains_real_personal_data": False,
        "licence": "CC0-1.0 (generated by this repository, no third-party data)",
    }
    (out / "dataset_meta.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/generated")
    ap.add_argument("--seed", type=int, default=20261010)
    ap.add_argument("--train", type=int, default=1500)
    ap.add_argument("--test", type=int, default=500)
    ap.add_argument("--novel", type=int, default=500)
    ap.add_argument("--demo", type=int, default=80)
    args = ap.parse_args()
    generate(Path(args.out), args.seed, args.train, args.test, args.novel, args.demo)
