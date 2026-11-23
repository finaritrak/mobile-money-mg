from __future__ import annotations

import json
from typing import Any, Dict
from urllib.parse import parse_qsl

from .errors import WebhookError


def load_body(body: Any) -> Dict[str, Any]:
    """Accept a webhook body as dict, JSON bytes/str or form-encoded bytes/str."""
    if isinstance(body, dict):
        return body
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    if not isinstance(body, str):
        raise WebhookError(f"Unsupported webhook body type: {type(body).__name__}")
    body = body.strip()
    if not body:
        raise WebhookError("Empty webhook body")
    if body.startswith(("{", "[")):
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise WebhookError(f"Invalid JSON in webhook body: {exc}") from exc
        if not isinstance(data, dict):
            raise WebhookError("Webhook JSON must be an object")
        return data
    pairs = parse_qsl(body, keep_blank_values=True) if "=" in body else []
    if not pairs:
        raise WebhookError("Unreadable webhook body")
    return dict(pairs)


def validate_amount(amount: int) -> int:
    """MGA has no decimals: only strictly positive integers are accepted."""
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError(f"amount must be an int in Ariary, got {amount!r}")
    if amount <= 0:
        raise ValueError("amount must be greater than 0")
    return amount
