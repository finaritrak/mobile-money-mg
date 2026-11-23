import httpx
import pytest

from mobile_money_mg import AirtelMoney, ConfigurationError, PaymentStatus, ProviderError, WebhookError

from .conftest import body

BASE = "https://openapiuat.airtel.africa"


@pytest.fixture
def airtel(api):
    api.add("POST", BASE + "/auth/oauth2/token", {"access_token": "at", "expires_in": "180"})
    return AirtelMoney(client_id="cid", client_secret="cs", http_client=api.client())


def ok(tx):
    return {
        "data": {"transaction": tx},
        "status": {"code": "200", "message": "SUCCESS", "result_code": "ESB000010", "success": True},
    }


def test_collect(api, airtel):
    api.add("POST", BASE + "/merchant/v1/payments/", ok({"id": "CMD-3", "status": "Success."}))
    payment = airtel.initiate_payment(amount=5000, phone="+261 33 12 345 67", reference="CMD-3")

    assert payment.status is PaymentStatus.PENDING
    assert payment.provider_id == "CMD-3"
    req = api.last("POST", "/merchant/v1/payments/")
    assert req.headers["X-Country"] == "MG"
    assert req.headers["X-Currency"] == "MGA"
    assert req.headers["Authorization"] == "Bearer at"
    data = body(req)
    assert data["subscriber"]["msisdn"] == "331234567"
    assert data["transaction"] == {"amount": 5000, "country": "MG", "currency": "MGA", "id": "CMD-3"}
    assert body(api.last("POST", "/auth/"))["grant_type"] == "client_credentials"


@pytest.mark.parametrize(
    "code, expected",
    [
        ("TS", PaymentStatus.SUCCESS),
        ("TF", PaymentStatus.FAILED),
        ("TIP", PaymentStatus.PENDING),
        ("TA", PaymentStatus.UNKNOWN),
    ],
)
def test_status(api, airtel, code, expected):
    api.add("POST", BASE + "/merchant/v1/payments/", ok({"id": "T1", "status": "Success."}))
    api.add(
        "GET",
        BASE + "/standard/v1/payments/T1",
        ok({"id": "T1", "status": code, "airtel_money_id": "MP210", "message": "msg"}),
    )
    payment = airtel.initiate_payment(amount=100, phone="0331234567", reference="T1")
    payment = airtel.get_status(payment)
    assert payment.status is expected
    assert payment.transaction_id == "MP210"


def test_business_error_raises(api, airtel):
    api.add(
        "POST",
        BASE + "/merchant/v1/payments/",
        {
            "status": {
                "code": "400",
                "message": "Duplicate id",
                "response_code": "DP00800001006",
                "success": False,
            }
        },
    )
    with pytest.raises(ProviderError) as exc:
        airtel.initiate_payment(amount=100, phone="0331234567", reference="T1")
    assert "Duplicate id" in str(exc.value)
    assert exc.value.status_code == 400


def test_network_error(api, airtel):
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    api.add("POST", BASE + "/merchant/v1/payments/", boom)
    with pytest.raises(ProviderError, match="network error"):
        airtel.initiate_payment(amount=100, phone="0331234567", reference="T1")


def test_webhook(airtel):
    event = airtel.parse_webhook(
        {"transaction": {"id": "T1", "message": "ok", "status_code": "TS", "airtel_money_id": "MP1"}}
    )
    assert event.status is PaymentStatus.SUCCESS
    assert event.reference == "T1"
    with pytest.raises(WebhookError):
        airtel.parse_webhook({"nope": 1})
    with pytest.raises(WebhookError):
        airtel.parse_webhook(b"")


def test_config():
    with pytest.raises(ConfigurationError):
        AirtelMoney(client_id="", client_secret="x")
    assert AirtelMoney(client_id="a", client_secret="b", sandbox=False).base_url == (
        "https://openapi.airtel.africa"
    )
