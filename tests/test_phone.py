import pytest

from mobile_money_mg import InvalidPhoneNumber, Operator, detect_operator, normalize
from mobile_money_mg.phone import to_international, to_national_without_zero


@pytest.mark.parametrize(
    "raw",
    [
        "0341234567",
        "034 12 345 67",
        "034-12-345-67",
        "+261341234567",
        "+261 34 12 345 67",
        "261341234567",
        "00261341234567",
        "341234567",
    ],
)
def test_normalize_accepts_common_formats(raw):
    assert normalize(raw) == "0341234567"


@pytest.mark.parametrize("raw", ["", "12345", "0201234567", "+33612345678", "03412345678", "abc"])
def test_normalize_rejects_invalid(raw):
    with pytest.raises(InvalidPhoneNumber):
        normalize(raw)


def test_normalize_rejects_non_string():
    with pytest.raises(InvalidPhoneNumber):
        normalize(341234567)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0341234567", Operator.MVOLA),
        ("0381234567", Operator.MVOLA),
        ("0321234567", Operator.ORANGE_MONEY),
        ("0371234567", Operator.ORANGE_MONEY),
        ("0331234567", Operator.AIRTEL_MONEY),
        ("0391234567", None),
    ],
)
def test_detect_operator(raw, expected):
    assert detect_operator(raw) is expected


def test_format_helpers():
    assert to_international("034 12 345 67") == "261341234567"
    assert to_national_without_zero("+261331234567") == "331234567"
