"""Django integration sketch.

Assumes an ``Order`` model with fields:
    reference, amount, operator, provider_id, notif_token, status, transaction_id

urls.py:
    path("pay/<str:reference>/", views.start_payment),
    path("webhooks/<str:operator>/", views.webhook),
"""

from __future__ import annotations

from django.db.models import Q
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from mobile_money_mg import MobileMoney, MobileMoneyError, Operator, Payment, PaymentStatus

from .models import Order  # type: ignore[import-not-found]

mm = MobileMoney.from_env()


def _payment(order: Order) -> Payment:
    return Payment(
        operator=Operator(order.operator),
        reference=order.reference,
        status=PaymentStatus(order.status),
        amount=order.amount,
        provider_id=order.provider_id,
        notif_token=order.notif_token,
    )


@require_http_methods(["POST"])
def start_payment(request: HttpRequest, reference: str) -> JsonResponse:
    order = get_object_or_404(Order, reference=reference)
    payment = mm.pay(amount=order.amount, phone=request.POST.get("phone"), reference=order.reference)
    order.operator = payment.operator.value
    order.provider_id = payment.provider_id
    order.notif_token = payment.notif_token
    order.status = payment.status.value
    order.save()
    return JsonResponse({"status": order.status, "redirect_url": payment.redirect_url})


@csrf_exempt
@require_http_methods(["POST", "PUT"])  # MVola uses PUT
def webhook(request: HttpRequest, operator: str):
    try:
        event = mm.parse_webhook(operator, request.body, dict(request.headers))
    except (MobileMoneyError, ValueError) as exc:
        return HttpResponseBadRequest(str(exc))

    lookup = Q(pk__in=[])
    if event.provider_id:
        lookup |= Q(provider_id=event.provider_id)
    if event.reference:
        lookup |= Q(reference=event.reference)
    if event.raw.get("notif_token"):  # Orange Money
        lookup |= Q(notif_token=event.raw["notif_token"])
    order = Order.objects.filter(lookup, operator=event.operator.value).first()
    if order is None:
        return HttpResponseNotFound()

    # Re-check with the operator before trusting the callback.
    payment = mm.status(_payment(order))
    order.status = payment.status.value
    order.transaction_id = payment.transaction_id
    order.save()
    return JsonResponse({"ok": True})
