"""Run with:  python examples/quickstart.py   (offline, uses the simulator)."""

from mobile_money_mg import MobileMoney

mm = MobileMoney.sandbox()  # swap for MobileMoney.from_env() with real credentials

payment = mm.pay(amount=15000, phone="034 12 345 67", reference="CMD-1042")
print("Started:", payment.operator.value, payment.status.value)

payment = mm.wait(payment, timeout=120)  # in production, prefer webhooks
print("Final:  ", payment.status.value, payment.transaction_id)

if payment.is_paid:
    print("✅ Deliver the order")
