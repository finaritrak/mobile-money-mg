"""Malagasy phone number helpers.

Accepts every format people actually type::

    034 12 345 67   0341234567   +261341234567   261 34 12 345 67   34-12-345-67
"""

from __future__ import annotations

import re
from typing import Optional

from .errors import InvalidPhoneNumber
from .models import Operator

COUNTRY_CODE = "261"

# Mobile prefixes per operator (after the leading 0).
PREFIXES = {
    "32": Operator.ORANGE_MONEY,
    "37": Operator.ORANGE_MONEY,
    "33": Operator.AIRTEL_MONEY,
    "34": Operator.MVOLA,
    "38": Operator.MVOLA,
}

_NON_DIGITS = re.compile(r"[^\d]")


def normalize(phone: str) -> str:
    """Return the number in local format: ``0XXXXXXXXX`` (10 digits).

    Raises:
        InvalidPhoneNumber: if it is not a Malagasy mobile number.
    """
    if not isinstance(phone, str):
        raise InvalidPhoneNumber(f"Phone number must be a string, got {type(phone).__name__}")

    digits = _NON_DIGITS.sub("", phone)
    if digits.startswith("00" + COUNTRY_CODE):
        digits = digits[2:]
    if digits.startswith(COUNTRY_CODE) and len(digits) == 12:
        digits = digits[3:]
    if len(digits) == 9:
        digits = "0" + digits

    if len(digits) != 10 or not digits.startswith("03"):
        raise InvalidPhoneNumber(f"Not a valid Malagasy mobile number: {phone!r}")
    return digits


def to_international(phone: str) -> str:
    """``0341234567`` → ``261341234567`` (no ``+``)."""
    return COUNTRY_CODE + normalize(phone)[1:]


def to_national_without_zero(phone: str) -> str:
    """``0341234567`` → ``341234567`` (format expected by Airtel's API)."""
    return normalize(phone)[1:]


def detect_operator(phone: str) -> Optional[Operator]:
    """Guess the operator from the prefix. Returns ``None`` if unknown.

    Note: numbers can be ported between operators in theory; the prefix is a
    very good heuristic in Madagascar, but let users override it in your UI.
    """
    return PREFIXES.get(normalize(phone)[1:3])
