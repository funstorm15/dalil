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
    missing). Similarity is token-wise (each token needs a close partner) —
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
            # one is a subset of the other
            shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            if len(shorter) == 1:
                s = next(iter(shorter))
                if len(s) == 1:  # initial: resolvable within a pair
                    return any(w.startswith(s) for w in longer)
                # a lone generic token ("Karimov" vs "Temur Karimov") is too
                # weak to claim identity — refuse rather than over-merge
                return False
            return True
    # token-wise similarity: every token of the longer name needs a close
    # partner — catches typos ("Abdurakhmon" ~ "Abdurahmon") without merging
    # distinct prefix-related names ("Temur" vs "Temurbek"), which whole-string
    # difflib would merge at 0.86
    longer, shorter = (ta, tb) if len(ta) >= len(tb) else (tb, ta)
    if not shorter:
        return False
    return all(
        max(difflib.SequenceMatcher(None, w, v).ratio() for v in shorter) >= threshold
        for w in longer
    )


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


# --- strict amount parsing (analyst / jury input) ------------------------
# Supported amount formats (documented in README "Input format"):
#   strict           plain digits "43500000"; thousands grouped by space / nbsp /
#                    apostrophe "43 500 000"; optional decimal part of 1-2 digits
#                    with "." or "," ("43500000.50", "45,5"); both separators
#                    together when unambiguous ("1.234.567,89", "1,234,567.89").
#                    A single "." or "," followed by exactly 3 digits ("4,500",
#                    "1.234") is AMBIGUOUS and rejected.
#   dot-thousands    "." groups thousands, "," is decimal (UZ/RU bank exports).
#   comma-thousands  "," groups thousands, "." is decimal (EN exports).
# All formats accept a scale word "4,5 млн" / "4.5 mln" / "300 тыс" and an
# optional currency suffix (UZS, сум, so'm). Anything else is rejected.
AMOUNT_FORMATS = ("strict", "dot-thousands", "comma-thousands")
_CURRENCY = re.compile(r"\s*(uzs|сум|сўм|so['ʻ’`]?m|sum)\.?\s*$", re.IGNORECASE)
_SCALED = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(млн|mln|million|тыс\.?|тыс|k)$", re.IGNORECASE)
_SCALE = {"млн": 1e6, "mln": 1e6, "million": 1e6, "тыс": 1e3, "тыс.": 1e3, "k": 1e3}


class AmountFormatError(ValueError):
    """Amount text that cannot be read unambiguously in the chosen format."""


def parse_amount_strict(raw: str | float | int, fmt: str = "strict") -> float:
    """Parse a UZS amount without guessing; raise AmountFormatError on doubt."""
    if fmt not in AMOUNT_FORMATS:
        raise AmountFormatError(f"unknown amount format '{fmt}'")
    if isinstance(raw, bool):
        raise AmountFormatError("boolean is not an amount")
    if isinstance(raw, (int, float)):
        val = float(raw)
    else:
        s = str(raw).replace(" ", " ").replace(" ", " ").strip()
        if not s:
            raise AmountFormatError("amount is missing")
        s = _CURRENCY.sub("", s).strip()
        m = _SCALED.match(s)
        if m:
            val = float(m.group(1).replace(",", ".")) * _SCALE[m.group(2).lower()]
        else:
            val = _parse_plain(s, fmt)
    if val != val or val in (float("inf"), float("-inf")):
        raise AmountFormatError("amount is not a finite number")
    if val <= 0:
        raise AmountFormatError("amount must be a positive UZS number")
    return val


def _parse_plain(s: str, fmt: str) -> float:
    if re.search(r"[^\d\s.,']", s):
        raise AmountFormatError("contains characters that are not part of a number")
    s = re.sub(r"(?<=\d)[\s'](?=\d{3}(?:\D|$))", "", s)  # space/apostrophe grouping
    if re.search(r"\s|'", s):
        raise AmountFormatError("thousands groups must have exactly 3 digits")
    if not re.fullmatch(r"\d[\d.,]*", s) or s[-1] in ".,":
        raise AmountFormatError("not a number")
    if fmt == "dot-thousands":
        group, dec = ".", ","
    elif fmt == "comma-thousands":
        group, dec = ",", "."
    else:
        dots, commas = s.count("."), s.count(",")
        if dots and commas:  # both present: the last one is the decimal mark
            dec = "." if s.rfind(".") > s.rfind(",") else ","
            group = "," if dec == "." else "."
        elif dots + commas == 0:
            return float(s)
        else:
            sep = "." if dots else ","
            if dots + commas > 1:  # repeated separator can only be grouping
                group, dec = sep, ("," if sep == "." else ".")
            else:
                frac = s.split(sep)[1]
                if len(frac) == 3:
                    raise AmountFormatError(
                        f"ambiguous separator: '{s}' could mean thousands or decimals — "
                        "write it without the separator, group thousands with spaces, "
                        "or choose an explicit amount format")
                group, dec = ("," if sep == "." else "."), sep
    if s.count(dec) > 1:
        raise AmountFormatError(f"more than one decimal mark '{dec}'")
    int_part, _, frac = s.partition(dec)
    if frac and not frac.isdigit():
        raise AmountFormatError("decimal part is not numeric")
    if group in int_part:
        groups = int_part.split(group)
        if not (1 <= len(groups[0]) <= 3) or any(len(g) != 3 for g in groups[1:]):
            raise AmountFormatError(f"thousands groups around '{group}' must have exactly 3 digits")
        int_part = "".join(groups)
    if not int_part.isdigit():
        raise AmountFormatError("not a number")
    return float(f"{int_part}.{frac}" if frac else int_part)


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
