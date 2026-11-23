"""mobile-money-mg — one Python API for MVola, Orange Money and Airtel Money in Madagascar."""

from .client import MobileMoney
from .errors import (
    AuthenticationError,
    ConfigurationError,
    InvalidPhoneNumber,
    MobileMoneyError,
    ProviderError,
    UnsupportedOperator,
    WebhookError,
)
from .models import Operator, Payment, PaymentStatus, WebhookEvent
from .phone import detect_operator, normalize
from .providers import AirtelMoney, MVola, OrangeMoney, Simulator

__version__ = "0.1.0"

__all__ = [
    "AirtelMoney",
    "AuthenticationError",
    "ConfigurationError",
    "InvalidPhoneNumber",
    "MVola",
    "MobileMoney",
    "MobileMoneyError",
    "Operator",
    "OrangeMoney",
    "Payment",
    "PaymentStatus",
    "ProviderError",
    "Simulator",
    "UnsupportedOperator",
    "WebhookError",
    "WebhookEvent",
    "__version__",
    "detect_operator",
    "normalize",
]
