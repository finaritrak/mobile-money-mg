"""Minimal FastAPI checkout with MVola, Orange Money and Airtel Money.

    pip install mobile-money-mg fastapi uvicorn
    MOBILE_MONEY_SIMULATOR=1 uvicorn examples.fastapi_app:app --reload

Then:  curl -X POST localhost:8000/checkout -H 'content-type: application/json' \
            -d '{"order_id": "CMD-1", "amount": 15000, "phone": "034 12 345 67"}'

Replace the in-memory ORDERS dict with your database.
"""

from __future__ import annotations

import hmac
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from mobile_money_mg import MobileMoney, MobileMoneyError, Operator, Payment, WebhookEvent

app = FastAPI(title="Checkout — mobile-money-mg")
mm = MobileMoney.from_env()  # reads MVOLA_*, ORANGE_*, AIRTEL_* (or MOBILE_MONEY_SIMULATOR=1)

ORDERS: Dict[str, Payment] = {}  # order_id -> Payment  (use a real DB in production)


class CheckoutIn(BaseModel):
    order_id: str
    amount: int
    phone: Optional[str] = None
    operator: Optional[Operator] = None


@app.post("/checkout")
def checkout(body: CheckoutIn) -> dict:
    try:
        payment = mm.pay(
            amount=body.amount, phone=body.phone, reference=body.order_id, operator=body.operator
        )
    except (MobileMoneyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ORDERS[body.order_id] = payment
    return {
        "status": payment.status.value,
        "operator": payment.operator.value,
        # Orange Money: redirect the customer here. MVola/Airtel: a PIN prompt is on their phone.
        "redirect_url": payment.redirect_url,
    }


@app.get("/orders/{order_id}")
def order_status(order_id: str) -> dict:
    payment = ORDERS.get(order_id)
    if payment is None:
        raise HTTPException(status_code=404)
    payment = mm.status(payment)
    return {"status": payment.status.value, "transaction_id": payment.transaction_id}


@app.api_route("/webhooks/{operator}", methods=["POST", "PUT"])
async def webhook(operator: Operator, request: Request) -> dict:
    """Callback URL to declare for each operator, e.g. https://shop.mg/webhooks/mvola.

    MVola calls back with PUT, Orange Money and Airtel Money with POST.
    """
    try:
        event = mm.parse_webhook(operator, await request.body(), dict(request.headers))
    except MobileMoneyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payment = _find_payment(event)
    if payment is None:
        raise HTTPException(status_code=404)

    # Never trust the callback alone: anyone can POST to a public URL.
    # Re-check with the operator, which is the source of truth.
    payment = mm.status(payment)
    ORDERS[payment.reference] = payment
    if payment.is_paid:
        pass  # mark the order as paid, send the receipt, ship…
    return {"ok": True}


def _find_payment(event: WebhookEvent) -> Optional[Payment]:
    """Match a callback to a stored payment (replace with a DB query)."""
    notif_token = event.raw.get("notif_token")  # Orange Money identifies payments this way
    for payment in ORDERS.values():
        if payment.operator != event.operator:
            continue
        if event.provider_id and event.provider_id == payment.provider_id:
            return payment
        if event.reference and event.reference == payment.reference:
            return payment
        if notif_token and payment.notif_token and hmac.compare_digest(notif_token, payment.notif_token):
            return payment
    return None
