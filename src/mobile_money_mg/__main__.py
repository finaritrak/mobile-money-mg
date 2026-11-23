"""``python -m mobile_money_mg`` — a 10-second offline demo using the simulator."""

from __future__ import annotations

import sys
from typing import List, Optional

from . import __version__
from .client import MobileMoney
from .phone import detect_operator

DEMO_NUMBERS = ["034 12 345 67", "032 98 765 13", "033 11 222 98"]


def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    numbers = args or DEMO_NUMBERS
    print(f"mobile-money-mg {__version__} — simulator demo (no network, no credentials)\n")
    mm = MobileMoney.sandbox()
    for i, number in enumerate(numbers, start=1):
        operator = detect_operator(number)
        label = operator.value if operator else "unknown operator"
        payment = mm.pay(amount=10000 * i, phone=number, reference=f"DEMO-{i}")
        payment = mm.wait(payment, timeout=0)
        print(
            f"  {payment.reference}  {number:<16} {label:<13} "
            f"{payment.amount:>7,} Ar  →  {payment.status.value.upper():<8} {payment.message or ''}"
        )
    print("\nTip: numbers ending in 13 fail, 98 expire, 99 stay pending. Everything else succeeds.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
