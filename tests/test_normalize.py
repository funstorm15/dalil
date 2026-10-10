"""Unit tests: normalization of messy UZS amounts, dates and UZ/RU names."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.normalize import (  # noqa: E402
    memo_hits,
    names_match,
    norm_name,
    norm_phone,
    parse_amount,
    parse_ts,
)


def test_amount_formats():
    assert parse_amount("43 500 000") == 43_500_000
    assert parse_amount("43.500.000") == 43_500_000
    assert parse_amount("4,5 млн") == 4_500_000
    assert parse_amount("4,500") == 4.5
    assert parse_amount(43_500_000) == 43_500_000
    assert parse_amount("1 234 567.89") == 1_234_567.89


def test_date_formats():
    assert parse_ts("2026-04-05 10:12:00").year == 2026
    assert parse_ts("05.04.2026 10:12").day == 5
    assert parse_ts("05/04/2026").month == 4  # day-first (UZ convention)
    assert parse_ts("garbage") is None


def test_names_transliteration_and_variants():
    assert norm_name("Temur Karimov") == "temur karimov"
    assert norm_name("Темур Каримов") == "temur karimov"
    assert norm_name("Savdo Markaz MChJ") == "savdo markaz"
    assert names_match("Temur Karimov", "temur karimov")
    assert names_match("Temur Karimov", "T. Karimov")
    assert names_match("Abdurahmon Karimov", "Абдурахмон Каримов")
    assert not names_match("Temur Karimov", "Dilnoza Yusupova")


def test_phone_normalization():
    assert norm_phone("+998 90 123 45 67") == "+998901234567"
    assert norm_phone("901234567") == "+998901234567"


def test_memo_lexicon_multilingual():
    assert "loan_repay" in memo_hits("qarz qaytarish")
    assert "crypto" in memo_hits("USDT otdam")
    assert "salary" in memo_hits("зарплата")
    assert "vague" in memo_hits("?????")
    assert memo_hits("") == []
