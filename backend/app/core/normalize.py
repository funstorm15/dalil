"""Normalization for UZS amounts, mixed date formats, names and memos.

Uzbekistan payment data arrives messy: amounts as "1 234 500", "1.234.500",
"4,5 млн", dates as ISO or dd.mm.yyyy, names in Latin Uzbek, Cyrillic Uzbek or
Russian, memos in any of the three. Everything the pipeline sees goes through
this module first.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

# Cyrillic -> Latin, covering Russian and Uzbek Cyrillic (ў ғ ҳ қ ё є).
_CYR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya", "є": "e", "і": "i", "ў": "o", "ғ": "g", "қ": "q",
    "ҳ": "h", "ң": "ng",
}

_CORP_SUFFIXES = re.compile(
    r"\b(mchj|mkk|ochj|qmb|ooo|ao|zao|oop|ip|llc|jsc|hh|хк|чп|тоо|боа)\b",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")

AMOUNT_RE = re.compile(r"(-?[\d][\d\s.,\u00a0]*)")
_MLN = re.compile(r"(\d+[.,]?\d*)\s*(млн|mln|million)", re.IGNORECASE)
_TYIS = re.compile(r"(\d+[.,]?\d*)\s*(тыс|тыч|тыс\.|k\b)", re.IGNORECASE)

PHONE_RE = re.compile(r"(?:\+?998|8)?[\s\-]?(?:9[01234578]|7[0-9])[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")


def translit_cyrillic(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(_CYR2LAT.get(ch, ch))
    return "".join(out)


def norm_name(name: str) -> str:
    """Canonical form for entity resolution: Latin, lowercase, no corp suffix,
    no punctuation, whitespace-collapsed."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name).strip()
    if re.search(r"[Ѐ-ӿ]", s):
        s = translit_cyrillic(s)
    s = s.replace("'", "").replace("`", "").replace("ʻ", "").replace("’", "")
    s = _CORP_SUFFIXES.sub(" ", s)
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip().lower()
    return s


def name_tokens(name: str) -> set[str]:
    n = norm_name(name)
    toks = set(n.split())
    # fold initials: "a karimov" ~ "abdurahmon karimov" when combined elsewhere
    return toks


def names_match(a: str, b: str, threshold: float = 0.86) -> bool:
    """True when two name strings likely denote the same party.

    Handles transliteration variants, initials and token subsets (first name
    missing). Uses difflib ratio over normalized strings plus token rules —
    deterministic, no external model needed.
    """
    import difflib

    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb:
        # expand single-letter initials against the other side ("T. Karimov" ~ "Temur Karimov")
        def _expand(toks: set[str], other: set[str]) -> set[str]:
            out: set[str] = set()
            for t in toks:
                if len(t) == 1:
                    cands = {o for o in other if o.startswith(t) and len(o) > 1}
                    out |= cands or {t}
                else:
                    out.add(t)
            return out

        ta_x, tb_x = _expand(ta, tb), _expand(tb, ta)
        if ta_x <= tb_x or tb_x <= ta_x:
            ta, tb = ta_x, tb_x
        if ta <= tb or tb <= ta:
            # one is a subset ("temur" vs "temur karimov", "a karimov" handled
            # by single-letter token check)
            shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            if len(shorter) == 1:
                s = next(iter(shorter))
                if len(s) == 1:  # initial
                    return any(w.startswith(s) for w in longer)
                return s in longer
            return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


def norm_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if digits.startswith("998"):
        digits = digits[3:]
    if len(digits) == 9 and digits[0] == "9":
        return "+998" + digits
    if len(digits) == 10 and digits.startswith("9989"):
        return "+998" + digits[3:]
    return "+" + digits


def parse_amount(raw: str | float | int) -> float:
    """Parse "1 234 500", "1.234.500", "45,5", "4,5 млн UZS" -> float UZS."""
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return 0.0
    m = _MLN.search(s)
    if m:
        return float(m.group(1).replace(",", ".")) * 1_000_000
    m = _TYIS.search(s)
    if m:
        return float(m.group(1).replace(",", ".")) * 1_000
    m = AMOUNT_RE.search(s.replace("\u00a0", " "))
    if not m:
        return 0.0
    num = m.group(1).strip()
    # Decide decimal/grouping separators.
    if " " in num and ("," in num or "." in num):
        num = num.replace(" ", "")
    if num.count(",") == 1 and num.count(".") == 1:
        # e.g. 1.234.567,89 vs 1,234,567.89 — last one wins
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif num.count(",") == 1:
        left, right = num.split(",")
        if len(right) == 3 and len(left) >= 1 and left.replace(".", "").isdigit() and "." not in left:
            # 4,500 -> grouping only if no decimal intent; treat as decimal
            num = num.replace(",", ".")
        else:
            num = num.replace(",", ".")
    elif num.count(".") > 1:
        num = num.replace(".", "")
    num = num.replace(" ", "")
    try:
        return float(num)
    except ValueError:
        return 0.0


def parse_ts(raw: str) -> datetime | None:
    s = str(raw).strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y%m%d%H%M%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except ValueError:
        return None


# Memo semantics: multilingual keyword lexicon (Latin Uzbek, Cyrillic Uzbek, Russian, English).
MEMO_LEXICON: dict[str, tuple[str, ...]] = {
    "salary": ("maosh", "оиди маош", "зарплата", "з/п", "salary", "avans", "аванс", "oylik"),
    "loan_repay": ("qarz", "каргар", "кредит", "kredit", "рассрочка", "to'lov", "оплата займа"),
    "trade_goods": ("tovar", "товар", "sotuv", "продажа", "опт", "opt", "xizmat", "услуга", "servis"),
    "crypto": ("usdt", "btc", "крипта", "kripto", "crypto", "binance", "bybit", "p2p buy", "tether"),
    "gambling": ("casino", "казино", "ставк", "bet", "betting", "aviator", "1xbet", "gambling"),
    "vague": ("perevod", "перевод", "prosto", "просто", "?????", "qqq", "depozit", "депозит", "halal"),
    "family": ("ona", "ota", "мама", "папа", "sister", "aka", "uka", "сестра", "брат"),
}


def memo_hits(memo: str) -> list[str]:
    m = (memo or "").lower()
    if not m:
        return []
    return [cat for cat, words in MEMO_LEXICON.items() if any(w in m for w in words)]


def round_amount(amount: float) -> bool:
    """Round in UZS terms: multiples of 500 000 (incl. 1m / 5m)."""
    if amount <= 0:
        return False
    return amount % 500_000 == 0
