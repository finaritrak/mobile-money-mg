"""Airtel Money — Airtel Africa Open API (Collection / USSD push).

Flow: you request a payment, the customer gets a USSD prompt and enters their PIN,
Airtel calls your callback URL (configured in the Airtel portal) and/or you poll.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import httpx

from .. import phone as phone_utils
from .._utils import load_body, validate_amount
from ..errors import ConfigurationError, ProviderError, WebhookError
from ..models import Operator, Payment, PaymentStatus, WebhookEvent
from .base import BaseProvider

SANDBOX_URL = "https://openapiuat.airtel.africa"
PRODUCTION_URL = "https://openapi.airtel.africa"
COLLECTION_PATH = "/merchant/v1/payments/"
STATUS_PATH = "/standard/v1/payments/"

_STATUS_MAP = {
    "TS": PaymentStatus.SUCCESS,  # Transaction Success
    "TF": PaymentStatus.FAILED,  # Transaction Failed
    "TIP": PaymentStatus.PENDING,  # Transaction In Progress
    "TA": PaymentStatus.UNKNOWN,  # Transaction Ambiguous — re-check later
}


class AirtelMoney(BaseProvider):
    """Airtel Money collection for Madagascar (country ``MG``, currency ``MGA``)."""

    operator = Operator.AIRTEL_MONEY

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        sandbox: bool = True,
        country: str = "MG",
        currency: str = "MGA",
        base_url: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not client_id or not client_secret:
            raise ConfigurationError("Airtel Money: client_id and client_secret are required")
        super().__init__(http_client=http_client, timeout=timeout)
        self.client_id = client_id
        self.client_secret = client_secret
        self.country = country.upper()
        self.currency = currency.upper()
        self.base_url = (base_url or (SANDBOX_URL if sandbox else PRODUCTION_URL)).rstrip("/")

    def _fetch_token(self) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"{self.base_url}/auth/oauth2/token",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "X-Country": self.country,
            "X-Currency": self.currency,
            "Content-Type": "application/json",
            "Accept": "*/*",
        }

    def initiate_payment(
        self,
        *,
        amount: int,
        reference: str,
        phone: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Payment:
        validate_amount(amount)
        if not phone:
            raise ValueError("Airtel Money: the customer's phone number is required")
        if not reference:
            raise ValueError("reference is required")
        customer = phone_utils.normalize(phone)
        body = {
            "reference": (description or reference)[:64],
            "subscriber": {
                "country": self.country,
                "currency": self.currency,
                # Airtel expects the number without country code and without the leading 0.
                "msisdn": phone_utils.to_national_without_zero(customer),
            },
            "transaction": {
                "amount": amount,
                "country": self.country,
                "currency": self.currency,
                "id": reference,
            },
        }
        data = self._request("POST", self.base_url + COLLECTION_PATH, headers=self._headers(), json=body)
        _raise_if_not_success(data)
        tx = (data.get("data") or {}).get("transaction") or {}
        return Payment(
            operator=self.operator,
            reference=reference,
            status=PaymentStatus.PENDING,
            amount=amount,
            phone=customer,
            provider_id=tx.get("id") or reference,
            message=(data.get("status") or {}).get("message"),
            raw=data,
        )

    def get_status(self, payment: Payment) -> Payment:
        tx_id = payment.provider_id or payment.reference
        data = self._request("GET", self.base_url + STATUS_PATH + tx_id, headers=self._headers())
        _raise_if_not_success(data)
        tx = (data.get("data") or {}).get("transaction") or {}
        payment.status = _map_status(tx.get("status"))
        payment.transaction_id = tx.get("airtel_money_id") or payment.transaction_id
        payment.message = tx.get("message") or payment.message
        payment.raw = data
        return payment

    def parse_webhook(self, body: Any, headers: Optional[Mapping[str, str]] = None) -> WebhookEvent:
        data = load_body(body)
        tx = data.get("transaction")
        if not isinstance(tx, dict):
            raise WebhookError("Airtel Money: no transaction object in callback")
        return WebhookEvent(
            operator=self.operator,
            status=_map_status(tx.get("status_code") or tx.get("status")),
            provider_id=tx.get("id"),
            reference=tx.get("id"),
            transaction_id=tx.get("airtel_money_id"),
            message=tx.get("message"),
            raw=data,
        )


def _raise_if_not_success(data: Dict[str, Any]) -> None:
    status = data.get("status") or {}
    if isinstance(status, dict) and status.get("success") is False:
        raise ProviderError(
            f"Airtel Money: {status.get('message') or 'request refused'} "
            f"({status.get('response_code') or status.get('result_code') or '?'})",
            status_code=_int_or_none(status.get("code")),
            payload=data,
        )


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_status(value: Any) -> PaymentStatus:
    return _STATUS_MAP.get(str(value or "").strip().upper(), PaymentStatus.UNKNOWN)
