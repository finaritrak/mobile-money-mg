"""Unified data models shared by every operator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class Operator(str, Enum):
    """Mobile Money operators supported in Madagascar."""

    MVOLA = "mvola"
    ORANGE_MONEY = "orange_money"
    AIRTEL_MONEY = "airtel_money"
    SIMULATOR = "simulator"


class PaymentStatus(str, Enum):
    """Normalised payment status, whatever the operator returns.

    ``PENDING``  the customer has not confirmed yet (or the operator is still processing)
    ``SUCCESS``  money received — you can deliver the order
    ``FAILED``   refused, cancelled, insufficient balance, wrong PIN…
    ``EXPIRED``  the payment window closed without a confirmation
    ``UNKNOWN``  the operator returned an ambiguous state: re-check later, never deliver
    """

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

    @property
    def is_final(self) -> bool:
        return self in (PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.EXPIRED)


@dataclass
class Payment:
    """A payment as seen by your application.

    Attributes:
        operator: which operator handles the payment.
        reference: *your* reference (order id, invoice number…). Unique per payment.
        status: normalised status.
        amount: amount in Ariary (MGA has no decimals).
        phone: customer's number in local format (``0341234567``), when known.
        provider_id: the identifier you must keep to query the status later
            (MVola ``serverCorrelationId``, Orange ``pay_token``, Airtel transaction id).
        transaction_id: the operator's final transaction number, once paid.
        redirect_url: Orange Money only — send the customer to this URL to pay.
        notif_token: Orange Money only — secret to check incoming notifications.
        raw: untouched operator response, for debugging and audits.
    """

    operator: Operator
    reference: str
    status: PaymentStatus
    amount: Optional[int] = None
    phone: Optional[str] = None
    provider_id: Optional[str] = None
    transaction_id: Optional[str] = None
    redirect_url: Optional[str] = None
    notif_token: Optional[str] = None
    message: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_paid(self) -> bool:
        return self.status is PaymentStatus.SUCCESS


@dataclass
class WebhookEvent:
    """A callback/notification received from an operator, already parsed."""

    operator: Operator
    status: PaymentStatus
    provider_id: Optional[str] = None
    reference: Optional[str] = None
    transaction_id: Optional[str] = None
    message: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)
