"""Orange Money — Web Payment API (Orange Developer).

Unlike MVola and Airtel, Orange Money Web Payment is a **redirect** flow:

1. you create a payment → Orange returns ``payment_url``, ``pay_token`` and ``notif_token``;
2. you redirect the customer to ``payment_url``; they confirm with an OTP from the USSD menu;
3. Orange POSTs a notification to ``notif_url`` and redirects the customer to ``return_url``;
4. you confirm with :meth:`OrangeMoney.get_status` before delivering.
"""

from __future__ import annotations

import base64
import hmac
from typing import Any, Dict, Mapping, Optional

import httpx

from .._utils import load_body, validate_amount
from ..errors import ConfigurationError, WebhookError
from ..models import Operator, Payment, PaymentStatus, WebhookEvent
from .base import BaseProvider

API_URL = "https://api.orange.com"
TOKEN_PATH = "/oauth/v3/token"
SANDBOX_SEGMENT = "dev"
MADAGASCAR_SEGMENT = "mg"
SANDBOX_CURRENCY = "OUV"
MADAGASCAR_CURRENCY = "MGA"

_STATUS_MAP = {
    "INITIATED": PaymentStatus.PENDING,
    "PENDING": PaymentStatus.PENDING,
    "SUCCESS": PaymentStatus.SUCCESS,
    "FAILED": PaymentStatus.FAILED,
    "EXPIRED": PaymentStatus.EXPIRED,
}


class OrangeMoney(BaseProvider):
    """Orange Money Web Payment.

    Args:
        authorization_header: the ready-made ``Basic …`` value shown in your
            Orange Developer application (or pass client_id/client_secret).
        merchant_key: the merchant key given by Orange at onboarding.
        return_url / cancel_url / notif_url: your URLs (notif_url must be public HTTPS).
        sandbox: ``True`` → ``/orange-money-webpay/dev/v1`` with currency ``OUV``.
        country: path segment for production (``"mg"`` for Madagascar).
    """

    operator = Operator.ORANGE_MONEY

    def __init__(
        self,
        *,
        merchant_key: str,
        return_url: str,
        cancel_url: str,
        notif_url: str,
        authorization_header: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        sandbox: bool = True,
        country: str = MADAGASCAR_SEGMENT,
        currency: Optional[str] = None,
        language: str = "fr",
        api_url: str = API_URL,
        token_path: str = TOKEN_PATH,
        http_client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        if not merchant_key:
            raise ConfigurationError("Orange Money: merchant_key is required")
        if not authorization_header and not (client_id and client_secret):
            raise ConfigurationError("Orange Money: pass authorization_header or client_id + client_secret")
        if not (return_url and cancel_url and notif_url):
            raise ConfigurationError("Orange Money: return_url, cancel_url and notif_url are required")
        super().__init__(http_client=http_client, timeout=timeout)
        self.merchant_key = merchant_key
        self.return_url = return_url
        self.cancel_url = cancel_url
        self.notif_url = notif_url
        self._auth = _auth_header(authorization_header, client_id, client_secret)
        self.api_url = api_url.rstrip("/")
        self.token_path = token_path
        segment = SANDBOX_SEGMENT if sandbox else country
        self.webpay_url = f"{self.api_url}/orange-money-webpay/{segment}/v1"
        self.currency = currency or (SANDBOX_CURRENCY if sandbox else MADAGASCAR_CURRENCY)
        self.language = language

    def _fetch_token(self) -> Dict[str, Any]:
        return self._request(
            "POST",
            self.api_url + self.token_path,
            headers={
                "Authorization": self._auth,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={"grant_type": "client_credentials"},
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def initiate_payment(
        self,
        *,
        amount: int,
        reference: str,
        phone: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Payment:
        """Create the payment page. ``phone`` is ignored: the customer types it on Orange's page."""
        validate_amount(amount)
        if not reference:
            raise ValueError("reference is required")
        body = {
            "merchant_key": self.merchant_key,
            "currency": self.currency,
            "order_id": reference,
            "amount": amount,
            "return_url": self.return_url,
            "cancel_url": self.cancel_url,
            "notif_url": self.notif_url,
            "lang": self.language,
            "reference": (description or reference)[:30],
        }
        data = self._request("POST", f"{self.webpay_url}/webpayment", headers=self._headers(), json=body)
        return Payment(
            operator=self.operator,
            reference=reference,
            status=PaymentStatus.PENDING,
            amount=amount,
            provider_id=data.get("pay_token"),
            redirect_url=data.get("payment_url"),
            notif_token=data.get("notif_token"),
            message=data.get("message"),
            raw=data,
        )

    def get_status(self, payment: Payment) -> Payment:
        if not payment.provider_id:
            raise ValueError("Orange Money: payment.provider_id (pay_token) is missing")
        if payment.amount is None:
            raise ValueError("Orange Money: payment.amount is required to query the status")
        data = self._request(
            "POST",
            f"{self.webpay_url}/transactionstatus",
            headers=self._headers(),
            json={
                "order_id": payment.reference,
                "amount": payment.amount,
                "pay_token": payment.provider_id,
            },
        )
        payment.status = _map_status(data.get("status"))
        payment.transaction_id = data.get("txnid") or payment.transaction_id
        payment.raw = data
        return payment

    def parse_webhook(
        self,
        body: Any,
        headers: Optional[Mapping[str, str]] = None,
        *,
        expected_notif_token: Optional[str] = None,
    ) -> WebhookEvent:
        """Parse an Orange notification.

        Pass ``expected_notif_token`` (saved from :meth:`initiate_payment`) to reject
        forged notifications. The comparison is constant-time.
        """
        data = load_body(body)
        status = data.get("status")
        if status is None:
            raise WebhookError("Orange Money: no status in notification")
        if expected_notif_token is not None:
            received = str(data.get("notif_token") or "")
            if not hmac.compare_digest(received, expected_notif_token):
                raise WebhookError("Orange Money: notif_token mismatch — notification rejected")
        return WebhookEvent(
            operator=self.operator,
            status=_map_status(status),
            transaction_id=data.get("txnid"),
            reference=data.get("order_id"),
            raw=data,
        )


def _auth_header(
    authorization_header: Optional[str], client_id: Optional[str], client_secret: Optional[str]
) -> str:
    if authorization_header:
        value = authorization_header.strip()
        return value if value.lower().startswith("basic ") else f"Basic {value}"
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _map_status(value: Any) -> PaymentStatus:
    return _STATUS_MAP.get(str(value or "").strip().upper(), PaymentStatus.UNKNOWN)
