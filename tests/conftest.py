from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Tuple

import httpx
import pytest

Handler = Callable[[httpx.Request], httpx.Response]


class FakeAPI:
    """Tiny router on top of httpx.MockTransport that records every request."""

    def __init__(self) -> None:
        self.routes: Dict[Tuple[str, str], Any] = {}
        self.requests: List[httpx.Request] = []

    def add(self, method: str, url: str, response: Any) -> None:
        """``response`` is a dict (JSON 200), an httpx.Response, or a callable."""
        self.routes[(method.upper(), url)] = response

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, str(request.url))
        if key not in self.routes:
            return httpx.Response(404, json={"error": f"no route for {key}"})
        resp = self.routes[key]
        if callable(resp):
            resp = resp(request)
        if isinstance(resp, httpx.Response):
            return resp
        return httpx.Response(200, json=resp)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    def last(self, method: str, url_part: str) -> httpx.Request:
        for req in reversed(self.requests):
            if req.method == method and url_part in str(req.url):
                return req
        raise AssertionError(f"no {method} request containing {url_part!r}")

    def count(self, url_part: str) -> int:
        return sum(1 for r in self.requests if url_part in str(r.url))


def body(request: httpx.Request) -> Any:
    return json.loads(request.content)


@pytest.fixture
def api() -> FakeAPI:
    return FakeAPI()
