import pytest

from mobile_money_mg import ConfigurationError, OrangeMoney, Payment, PaymentStatus, WebhookError

TOKEN = "https://api.orange.com/oauth/v3/token"
DEV = "https://api.orange.com/orange-money-webpay/dev/v1"
MG = "https://api.orange.com/orange-money-webpay/mg/v1"

from .conftest import body  # noqa: E402


def make(api, **overrides):
    api.add("POST", TOKEN, {"access_token": "om-tok", "expires_in": "7776000"})
    params = dict(
        merchant_key="mk",
        authorization_header="Basic abc==",
        return_url="https://shop.mg/ok",
        cancel_url="https://shop.mg/cancel",
        notif_url="https://shop.mg/webhooks/orange",
        http_client=api.client(),
    )
    params.update(overrides)
    return OrangeMoney(**params)


def test_initiate_returns_redirect(api):
    om = make(api)
    api.add(
        "POST",
        DEV + "/webpayment",
        {
            "status": 201,
            "message": "OK",
            "pay_token": "pt-1",
            "payment_url": "https://webpayment.orange-money.com/payment/pay_token/pt-1",
            "notif_token": "nt-1",
        },
    )
    payment = om.initiate_payment(amount=25000, reference="CMD-7")

    assert payment.status is PaymentStatus.PENDING
    assert payment.provider_id == "pt-1"
    assert payment.redirect_url.endswith("pt-1")
    assert payment.notif_token == "nt-1"

    token_req = api.last("POST", "/oauth/")
    assert token_req.headers["Authorization"] == "Basic abc=="
    data = body(api.last("POST", "/webpayment"))
    assert data["currency"] == "OUV"
    assert data["order_id"] == "CMD-7"
    assert data["amount"] == 25000
    assert data["merchant_key"] == "mk"
    assert data["notif_url"] == "https://shop.mg/webhooks/orange"


def test_production_uses_country_and_mga(api):
    om = make(api, sandbox=False)
    api.add("POST", MG + "/webpayment", {"pay_token": "p", "payment_url": "u", "notif_token": "n"})
    om.initiate_payment(amount=1000, reference="R")
    assert body(api.last("POST", "/webpayment"))["currency"] == "MGA"


def test_client_credentials_build_basic_header(api):
    om = make(api, authorization_header=None, client_id="id", client_secret="sec")
    assert om._auth == "Basic aWQ6c2Vj"
    om2 = make(api, authorization_header="abc==")
    assert om2._auth == "Basic abc=="


@pytest.mark.parametrize(
    "remote, expected",
    [
        ("INITIATED", PaymentStatus.PENDING),
        ("PENDING", PaymentStatus.PENDING),
        ("SUCCESS", PaymentStatus.SUCCESS),
        ("FAILED", PaymentStatus.FAILED),
        ("EXPIRED", PaymentStatus.EXPIRED),
        ("???", PaymentStatus.UNKNOWN),
    ],
)
def test_status(api, remote, expected):
    om = make(api)
    api.add("POST", DEV + "/transactionstatus", {"status": remote, "txnid": "MP2311"})
    payment = Payment(
        operator=om.operator, reference="CMD-7", status=PaymentStatus.PENDING, amount=500, provider_id="pt"
    )
    payment = om.get_status(payment)
    assert payment.status is expected
    assert body(api.last("POST", "transactionstatus")) == {
        "order_id": "CMD-7",
        "amount": 500,
        "pay_token": "pt",
    }


def test_status_requires_token_and_amount(api):
    om = make(api)
    with pytest.raises(ValueError):
        om.get_status(Payment(operator=om.operator, reference="x", status=PaymentStatus.PENDING, amount=1))
    with pytest.raises(ValueError):
        om.get_status(
            Payment(operator=om.operator, reference="x", status=PaymentStatus.PENDING, provider_id="p")
        )


def test_webhook_checks_notif_token(api):
    om = make(api)
    payload = {"status": "SUCCESS", "notif_token": "nt-1", "txnid": "MP1"}
    event = om.parse_webhook(payload, expected_notif_token="nt-1")
    assert event.status is PaymentStatus.SUCCESS
    assert event.transaction_id == "MP1"
    with pytest.raises(WebhookError):
        om.parse_webhook(payload, expected_notif_token="forged")
    with pytest.raises(WebhookError):
        om.parse_webhook({"notif_token": "nt-1"})


def test_config_errors(api):
    with pytest.raises(ConfigurationError):
        make(api, merchant_key="")
    with pytest.raises(ConfigurationError):
        make(api, authorization_header=None)
    with pytest.raises(ConfigurationError):
        make(api, notif_url="")
