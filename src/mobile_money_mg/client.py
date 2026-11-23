"""One client for every operator: routes each payment to the right provider."""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

from . import phone as phone_utils
from .errors import ConfigurationError, UnsupportedOperator, WebhookError
from .models import Operator, Payment, WebhookEvent
from .providers import AirtelMoney, BaseProvider, MVola, OrangeMoney, Simulator

OperatorLike = Union[Operator, str]


class MobileMoney:
    """Unified entry point.

    Example::

        mm = MobileMoney(mvola=MVola(...), airtel=AirtelMoney(...))
        payment = mm.pay(amount=15000, phone="034 12 345 67", reference="CMD-1042")
        payment = mm.wait(payment)
        if payment.is_paid:
            deliver_order()

    The operator is detected from the phone prefix (034/038 → MVola,
    032/037 → Orange Money, 033 → Airtel Money) unless you pass ``operator=``.
    """

    def __init__(
        self,
        *,
        mvola: Optional[MVola] = None,
        orange: Optional[OrangeMoney] = None,
        airtel: Optional[AirtelMoney] = None,
        simulator: Optional[Simulator] = None,
    ) -> None:
        self._providers: Dict[Operator, BaseProvider] = {}
        if mvola:
            self._providers[Operator.MVOLA] = mvola
        if orange:
            self._providers[Operator.ORANGE_MONEY] = orange
        if airtel:
            self._providers[Operator.AIRTEL_MONEY] = airtel
        self._simulator = simulator
        if simulator:
            self._providers[Operator.SIMULATOR] = simulator
        if not self._providers:
            raise ConfigurationError("Configure at least one provider (or use MobileMoney.sandbox())")

    # ------------------------------------------------------------ builders

    @classmethod
    def sandbox(cls) -> MobileMoney:
        """Fully offline client: every payment goes to the simulator."""
        return cls(simulator=Simulator())

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> MobileMoney:
        """Build the client from environment variables (see README for the list).

        Only the operators whose variables are present are enabled.
        ``MOBILE_MONEY_SIMULATOR=1`` routes everything to the simulator.
        """
        env = os.environ if environ is None else environ
        if _truthy(env.get("MOBILE_MONEY_SIMULATOR")):
            return cls.sandbox()
        sandbox = not _truthy(env.get("MOBILE_MONEY_PRODUCTION"))

        mvola = None
        if env.get("MVOLA_CONSUMER_KEY"):
            mvola = MVola(
                consumer_key=env["MVOLA_CONSUMER_KEY"],
                consumer_secret=_required(env, "MVOLA_CONSUMER_SECRET"),
                merchant_number=_required(env, "MVOLA_MERCHANT_NUMBER"),
                partner_name=_required(env, "MVOLA_PARTNER_NAME"),
                callback_url=env.get("MVOLA_CALLBACK_URL"),
                sandbox=sandbox,
            )
        orange = None
        if env.get("ORANGE_MERCHANT_KEY"):
            orange = OrangeMoney(
                merchant_key=env["ORANGE_MERCHANT_KEY"],
                authorization_header=env.get("ORANGE_AUTHORIZATION_HEADER"),
                client_id=env.get("ORANGE_CLIENT_ID"),
                client_secret=env.get("ORANGE_CLIENT_SECRET"),
                return_url=_required(env, "ORANGE_RETURN_URL"),
                cancel_url=_required(env, "ORANGE_CANCEL_URL"),
                notif_url=_required(env, "ORANGE_NOTIF_URL"),
                sandbox=sandbox,
            )
        airtel = None
        if env.get("AIRTEL_CLIENT_ID"):
            airtel = AirtelMoney(
                client_id=env["AIRTEL_CLIENT_ID"],
                client_secret=_required(env, "AIRTEL_CLIENT_SECRET"),
                sandbox=sandbox,
            )
        return cls(mvola=mvola, orange=orange, airtel=airtel)

    # ------------------------------------------------------------------ API

    @property
    def operators(self) -> List[Operator]:
        """Operators currently configured."""
        return list(self._providers)

    def provider(self, operator: OperatorLike) -> BaseProvider:
        op = Operator(operator)
        if self._simulator is not None and op is not Operator.SIMULATOR:
            return self._simulator
        try:
            return self._providers[op]
        except KeyError:
            raise UnsupportedOperator(f"No provider configured for {op.value}") from None

    def pay(
        self,
        *,
        amount: int,
        reference: str,
        phone: Optional[str] = None,
        operator: Optional[OperatorLike] = None,
        description: Optional[str] = None,
    ) -> Payment:
        """Start a payment with the right operator.

        For Orange Money, redirect the customer to ``payment.redirect_url``.
        For MVola / Airtel Money, the customer receives a PIN prompt on their phone.
        """
        op = self._resolve_operator(phone, operator)
        return self.provider(op).initiate_payment(
            amount=amount, reference=reference, phone=phone, description=description
        )

    def status(self, payment: Payment) -> Payment:
        """Refresh ``payment`` from the operator (source of truth)."""
        return self.provider(payment.operator).get_status(payment)

    def wait(
        self,
        payment: Payment,
        *,
        timeout: float = 180.0,
        interval: float = 5.0,
        max_interval: float = 20.0,
        sleep: Callable[[float], Any] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> Payment:
        """Poll until the payment is final or ``timeout`` seconds have passed.

        Uses a gentle back-off (×1.5, capped at ``max_interval``) to respect rate limits.
        Prefer webhooks in production; this is handy for scripts, bots and kiosks.
        """
        deadline = clock() + timeout
        delay = interval
        while True:
            payment = self.status(payment)
            if payment.status.is_final:
                return payment
            remaining = deadline - clock()
            if remaining <= 0:
                return payment
            sleep(min(delay, remaining))
            delay = min(delay * 1.5, max_interval)

    def parse_webhook(
        self,
        operator: OperatorLike,
        body: Any,
        headers: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> WebhookEvent:
        """Parse a callback. **Never deliver on a webhook alone** — use :meth:`confirm_webhook`."""
        return self.provider(operator).parse_webhook(body, headers, **kwargs)

    def confirm_webhook(
        self,
        payment: Payment,
        body: Any,
        headers: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> Payment:
        """Parse the callback, then re-check the status directly with the operator.

        Anyone can POST to a public URL: the second call is what makes the result
        trustworthy. Returns the refreshed :class:`Payment`.
        """
        event = self.parse_webhook(payment.operator, body, headers, **kwargs)
        ids = {payment.provider_id, payment.reference} - {None}
        received = {event.provider_id, event.reference} - {None}
        if received and not (ids & received):
            raise WebhookError("Webhook does not belong to this payment")
        return self.status(payment)

    def close(self) -> None:
        for provider in self._providers.values():
            provider.close()

    def __enter__(self) -> MobileMoney:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- helpers

    def _resolve_operator(self, phone: Optional[str], operator: Optional[OperatorLike]) -> Operator:
        if operator is not None:
            return Operator(operator)
        if self._simulator is not None:
            return Operator.SIMULATOR
        if not phone:
            raise ValueError("Pass phone= (to detect the operator) or operator=")
        detected = phone_utils.detect_operator(phone)
        if detected is None:
            raise UnsupportedOperator(f"Unknown operator for {phone!r}; pass operator= explicitly")
        return detected


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key)
    if not value:
        raise ConfigurationError(f"Missing environment variable {key}")
    return value
