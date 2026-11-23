"""Offline simulator: develop and test your checkout without any operator account.

The outcome depends on the **last two digits** of the customer's number::

    …13  → FAILED   (e.g. insufficient balance)
    …98  → EXPIRED  (customer never confirmed)
    …99  → stays PENDING forever (useful to test your timeouts)
    anything else → SUCCESS

The first :meth:`get_status` call after initiation returns the final result,
so a typical "initiate → poll" loop behaves like the real thing.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, Mapping, Optional

from .. import phone as phone_utils
from .._utils import load_body, validate_amount
from ..errors import ProviderError, WebhookError
from ..models import Operator, Payment, PaymentStatus, WebhookEvent
from .base import BaseProvider

_OUTCOMES = {
    "13": (PaymentStatus.FAILED, "Solde insuffisant (simulation)"),
    "98": (PaymentStatus.EXPIRED, "Délai de confirmation dépassé (simulation)"),
    "99": (PaymentStatus.PENDING, "En attente de confirmation (simulation)"),
}


class Simulator(BaseProvider):
    """In-memory provider. Thread-safe, no network, no credentials."""

    operator = Operator.SIMULATOR

    def __init__(self) -> None:
        # No HTTP client needed; keep BaseProvider happy with a lazy dummy.
        self._payments: Dict[str, Payment] = {}
        self._lock = threading.Lock()
        self._token = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()
        self._owns_client = False

    def _fetch_token(self) -> Dict[str, Any]:  # pragma: no cover - never called
        return {"access_token": "simulator", "expires_in": 3600}

    def initiate_payment(
        self,
        *,
        amount: int,
        reference: str,
        phone: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Payment:
        validate_amount(amount)
        if not reference:
            raise ValueError("reference is required")
        customer = phone_utils.normalize(phone) if phone else None
        with self._lock:
            if reference in self._payments:
                raise ProviderError(f"simulator: duplicate reference {reference!r}", status_code=409)
            payment = Payment(
                operator=self.operator,
                reference=reference,
                status=PaymentStatus.PENDING,
                amount=amount,
                phone=customer,
                provider_id=f"sim-{uuid.uuid4()}",
                message=description,
                raw={"simulated": True},
            )
            self._payments[reference] = payment
            return _copy(payment)

    def get_status(self, payment: Payment) -> Payment:
        with self._lock:
            stored = self._payments.get(payment.reference)
            if stored is None:
                raise ProviderError(f"simulator: unknown payment {payment.reference!r}", status_code=404)
            if not stored.status.is_final:
                status, message = _OUTCOMES.get(
                    (stored.phone or "")[-2:], (PaymentStatus.SUCCESS, "Paiement reçu (simulation)")
                )
                stored.status = status
                stored.message = message
                if status is PaymentStatus.SUCCESS:
                    stored.transaction_id = f"SIM{uuid.uuid4().int % 10**10:010d}"
            payment.status = stored.status
            payment.message = stored.message
            payment.transaction_id = stored.transaction_id
            payment.raw = {"simulated": True}
            return payment

    def webhook_payload(self, payment: Payment) -> Dict[str, Any]:
        """Build the callback body the simulator would send — post it to your own endpoint."""
        current = self.get_status(_copy(payment))
        return {
            "reference": current.reference,
            "provider_id": current.provider_id,
            "status": current.status.value,
            "transaction_id": current.transaction_id,
            "message": current.message,
        }

    def parse_webhook(self, body: Any, headers: Optional[Mapping[str, str]] = None) -> WebhookEvent:
        data = load_body(body)
        try:
            status = PaymentStatus(data.get("status"))
        except ValueError as exc:
            raise WebhookError(f"simulator: invalid status {data.get('status')!r}") from exc
        return WebhookEvent(
            operator=self.operator,
            status=status,
            provider_id=data.get("provider_id"),
            reference=data.get("reference"),
            transaction_id=data.get("transaction_id"),
            message=data.get("message"),
            raw=data,
        )

    def close(self) -> None:
        return None


def _copy(payment: Payment) -> Payment:
    return Payment(**{k: getattr(payment, k) for k in payment.__dataclass_fields__})
