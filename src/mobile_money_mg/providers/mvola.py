"""MVola (Telma) — Merchant Pay API 1.0.

Flow: the merchant initiates a payment, the customer receives a USSD prompt and
types their PIN, then MVola calls ``X-Callback-URL`` (PUT) and/or you poll the status.
"""

from __future__ import annotations

import base64
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

import httpx

from .. import phone as phone_utils
from .._utils import load_body, validate_amount
from ..errors import ConfigurationError, WebhookError
from ..models import Operator, Payment, PaymentStatus, WebhookEvent
from .base import BaseProvider

SANDBOX_URL = "https://devapi.mvola.mg"
PRODUCTION_URL = "https://api.mvola.mg"
MERCHANT_PAY_PATH = "/mvola/mm/transactions/type/merchantpay/1.0.0/"

# Sandbox test numbers published with the MVola developer documentation.
SANDBOX_TEST_NUMBERS = ("0343500003", "0343500004")

_STATUS_MAP = {
    "pending": PaymentStatus.PENDING,
    "completed": PaymentStatus.SUCCESS,
    "success": PaymentStatus.SUCCESS,
    "failed": PaymentStatus.FAILED,
}

# descriptionText: no special characters except - . _ , (MVola rejects the rest).
_DESCRIPTION_FORBIDDEN = re.compile(r"[^0-9A-Za-zÀ-ÿ \-._,]")
_DESCRIPTION_MAX = 40


class MVola(BaseProvider):
    """MVola Merchant Pay.

    Args:
        consumer_key / consumer_secret: from your application on the MVola developer portal.
        merchant_number: the MVola number that receives the money (e.g. ``0343500004``).
        partner_name: your company / app name, sent with each request.
        callback_url: public HTTPS URL where MVola sends the final result (optional).
        sandbox: ``True`` to use the MVola sandbox (default).
        language: ``"FR"`` or ``"MG"`` for messages shown to the customer.
    """

    operator = Operator.MVOLA

    def __init__(
        self,
        *,
        consumer_key: str,
        consumer_secret: str,
        merchant_number: str,
        partner_name: str,
        callback_url: Optional[str] = None,
        sandbox: bool = True,
        language: str = "FR",
        base_url: Optional[str] = None,
        foreign_currency: str = "USD",
        foreign_amount: str = "1",
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not consumer_key or not consumer_secret:
            raise ConfigurationError("MVola: consumer_key and consumer_secret are required")
        if not partner_name:
            raise ConfigurationError("MVola: partner_name is required")
        if language.upper() not in ("FR", "MG"):
            raise ConfigurationError("MVola: language must be 'FR' or 'MG'")
        super().__init__(http_client=http_client, timeout=timeout)
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.merchant_number = phone_utils.normalize(merchant_number)
        self.partner_name = partner_name[:50]
        self.callback_url = callback_url
        self.language = language.upper()
        self.base_url = (base_url or (SANDBOX_URL if sandbox else PRODUCTION_URL)).rstrip("/")
        # MVola's reference payload carries a foreign-currency hint in metadata.
        self.foreign_currency = foreign_currency
        self.foreign_amount = foreign_amount

    # -------------------------------------------------------------- tokens

    def _fetch_token(self) -> Dict[str, Any]:
        credentials = f"{self.consumer_key}:{self.consumer_secret}".encode()
        return self._request(
            "POST",
            f"{self.base_url}/token",
            headers={
                "Authorization": "Basic " + base64.b64encode(credentials).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
                "Cache-Control": "no-cache",
            },
            data={"grant_type": "client_credentials", "scope": "EXT_INT_MVOLA_SCOPE"},
        )

    def _headers(self, *, with_callback: bool = False) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Version": "1.0",
            "X-CorrelationID": str(uuid.uuid4()),
            "UserLanguage": self.language,
            "UserAccountIdentifier": f"msisdn;{self.merchant_number}",
            "partnerName": self.partner_name,
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        }
        if with_callback and self.callback_url:
            headers["X-Callback-URL"] = self.callback_url
        return headers

    # ----------------------------------------------------------------- API

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
            raise ValueError("MVola: the customer's phone number is required")
        if not reference:
            raise ValueError("reference is required")
        customer = phone_utils.normalize(phone)

        body = {
            "amount": str(amount),
            "currency": "Ar",
            "descriptionText": clean_description(description or f"Paiement {reference}"),
            "requestingOrganisationTransactionReference": reference,
            "requestDate": _now_iso(),
            "originalTransactionReference": reference,
            "debitParty": [{"key": "msisdn", "value": customer}],
            "creditParty": [{"key": "msisdn", "value": self.merchant_number}],
            "metadata": [
                {"key": "partnerName", "value": self.partner_name},
                {"key": "fc", "value": self.foreign_currency},
                {"key": "amountFc", "value": self.foreign_amount},
            ],
        }
        data = self._request(
            "POST",
            self.base_url + MERCHANT_PAY_PATH,
            headers=self._headers(with_callback=True),
            json=body,
        )
        return Payment(
            operator=self.operator,
            reference=reference,
            status=_map_status(data.get("status")),
            amount=amount,
            phone=customer,
            provider_id=data.get("serverCorrelationId"),
            raw=data,
        )

    def get_status(self, payment: Payment) -> Payment:
        if not payment.provider_id:
            raise ValueError("MVola: payment.provider_id (serverCorrelationId) is missing")
        data = self._request(
            "GET",
            f"{self.base_url}{MERCHANT_PAY_PATH}status/{payment.provider_id}",
            headers=self._headers(),
        )
        payment.status = _map_status(data.get("status"))
        payment.transaction_id = data.get("objectReference") or payment.transaction_id
        payment.raw = data
        return payment

    def get_transaction(self, transaction_id: str) -> Dict[str, Any]:
        """Full details of a completed transaction (amount, fees, parties…)."""
        return self._request(
            "GET",
            f"{self.base_url}{MERCHANT_PAY_PATH}{transaction_id}",
            headers=self._headers(),
        )

    def parse_webhook(self, body: Any, headers: Optional[Mapping[str, str]] = None) -> WebhookEvent:
        data = load_body(body)
        status = data.get("transactionStatus") or data.get("status")
        if status is None:
            raise WebhookError("MVola: no transactionStatus in callback")
        return WebhookEvent(
            operator=self.operator,
            status=_map_status(status),
            provider_id=data.get("serverCorrelationId"),
            reference=data.get("requestingOrganisationTransactionReference")
            or data.get("originalTransactionReference"),
            transaction_id=data.get("transactionReference") or data.get("objectReference"),
            raw=data,
        )


def clean_description(text: str) -> str:
    """Strip characters MVola refuses and cut to 40 characters."""
    cleaned = _DESCRIPTION_FORBIDDEN.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:_DESCRIPTION_MAX] or "Paiement"


def _map_status(value: Any) -> PaymentStatus:
    return _STATUS_MAP.get(str(value or "").strip().lower(), PaymentStatus.UNKNOWN)


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
