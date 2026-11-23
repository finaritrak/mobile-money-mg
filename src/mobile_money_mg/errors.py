"""Exceptions raised by the SDK. All inherit from :class:`MobileMoneyError`."""

from __future__ import annotations

from typing import Any, Optional


class MobileMoneyError(Exception):
    """Base class for every error raised by mobile-money-mg."""


class ConfigurationError(MobileMoneyError):
    """Missing or invalid credentials / settings."""


class InvalidPhoneNumber(MobileMoneyError, ValueError):
    """The phone number is not a valid Malagasy mobile number."""


class UnsupportedOperator(MobileMoneyError):
    """No provider is configured for the operator of this phone number."""


class AuthenticationError(MobileMoneyError):
    """The operator refused the credentials (bad key/secret, expired token…)."""


class ProviderError(MobileMoneyError):
    """The operator answered with an error.

    Attributes:
        status_code: HTTP status returned by the operator (``None`` on network errors).
        payload: decoded response body, when available.
    """

    def __init__(self, message: str, *, status_code: Optional[int] = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class WebhookError(MobileMoneyError):
    """The webhook payload is malformed or could not be authenticated."""
