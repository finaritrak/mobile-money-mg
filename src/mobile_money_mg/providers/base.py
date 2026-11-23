"""Common plumbing for every provider: HTTP client, token cache, error mapping."""

from __future__ import annotations

import abc
import logging
import threading
import time
from typing import Any, Dict, Mapping, Optional

import httpx

from ..errors import AuthenticationError, ProviderError
from ..models import Operator, Payment, WebhookEvent

logger = logging.getLogger("mobile_money_mg")

DEFAULT_TIMEOUT = 30.0
# Refresh tokens a bit before they really expire, to avoid edge-of-expiry failures.
TOKEN_SAFETY_MARGIN = 60


class BaseProvider(abc.ABC):
    """Interface implemented by every operator."""

    operator: Operator

    def __init__(
        self,
        *,
        http_client: Optional[httpx.Client] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._http = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None
        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    # ------------------------------------------------------------------ API

    @abc.abstractmethod
    def initiate_payment(
        self,
        *,
        amount: int,
        reference: str,
        phone: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Payment:
        """Start a payment. Most operators send a PIN prompt to the customer's phone."""

    @abc.abstractmethod
    def get_status(self, payment: Payment) -> Payment:
        """Ask the operator for the current state of ``payment``."""

    @abc.abstractmethod
    def parse_webhook(self, body: Any, headers: Optional[Mapping[str, str]] = None) -> WebhookEvent:
        """Turn the raw callback body (bytes, str or dict) into a :class:`WebhookEvent`."""

    # -------------------------------------------------------------- tokens

    @abc.abstractmethod
    def _fetch_token(self) -> Dict[str, Any]:
        """Request a fresh OAuth token. Must return the decoded JSON."""

    def _access_token(self) -> str:
        with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token
            data = self._fetch_token()
            token = data.get("access_token")
            if not token:
                raise AuthenticationError(f"{self.operator.value}: no access_token in response")
            try:
                expires_in = int(data.get("expires_in") or 3600)
            except (TypeError, ValueError):
                expires_in = 3600
            self._token = str(token)
            self._token_expires_at = time.monotonic() + max(expires_in - TOKEN_SAFETY_MARGIN, 30)
            return self._token

    def clear_token(self) -> None:
        """Forget the cached token (next call fetches a new one)."""
        with self._token_lock:
            self._token = None
            self._token_expires_at = 0.0

    # ---------------------------------------------------------------- http

    def _request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        try:
            response = self._http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.operator.value}: network error: {exc}") from exc

        payload = _decode(response)
        if response.status_code in (401, 403):
            # A stale token is the usual culprit: drop it so the next call re-authenticates.
            self.clear_token()
            raise AuthenticationError(
                f"{self.operator.value}: authentication refused (HTTP {response.status_code})"
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.operator.value}: HTTP {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
        logger.debug("%s %s -> %s", method, url, response.status_code)
        if not isinstance(payload, dict):
            return {"data": payload}
        return payload

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> BaseProvider:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _decode(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {"text": response.text}
