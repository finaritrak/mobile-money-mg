import base64
import json

import httpx
import pytest

from mobile_money_mg import (
    AuthenticationError,
    ConfigurationError,
    MVola,
    PaymentStatus,
    ProviderError,
    WebhookError,
)
from mobile_money_mg.providers.mvola import clean_description

from .conftest import body

BASE = "https://devapi.mvola.mg"
PAY = BASE + "/mvola/mm/transactions/type/merchantpay/1.0.0/"


@pytest.fixture
def mvola(api):
    api.add("POST", BASE + "/token", {"access_token": "tok-1", "expires_in": 3600})
    return MVola(
        consumer_key="key",
        consumer_secret="secret",
        merchant_number="034 35 000 04",
        partner_name="Katonne",
        callback_url="https://example.mg/webhooks/mvola",
        http_client=api.client(),
    )


def test_initiate_payment_sends_expected_request(api, mvola):
    api.add(
        "POST",
        PAY,
        {"status": "pending", "serverCorrelationId": "corr-1", "notificationMethod": "callback"},
    )
    payment = mvola.initiate_payment(
        amount=15000, phone="+261 34 35 000 03", reference="CMD-1", description="Commande #1 (café)"
    )

    assert payment.status is PaymentStatus.PENDING
    assert payment.provider_id == "corr-1"
    assert payment.phone == "0343500003"

    token_req = api.last("POST", "/token")
    expected = "Basic " + base64.b64encode(b"key:secret").decode()
    assert token_req.headers["Authorization"] == expected
    assert b"scope=EXT_INT_MVOLA_SCOPE" in token_req.content

    req = api.last("POST", "merchantpay")
    assert req.headers["Authorization"] == "Bearer tok-1"
    assert req.headers["Version"] == "1.0"
    assert req.headers["UserAccountIdentifier"] == "msisdn;0343500004"
    assert req.headers["X-Callback-URL"] == "https://example.mg/webhooks/mvola"
    assert req.headers["UserLanguage"] == "FR"
    assert req.headers["X-CorrelationID"]
    data = body(req)
    assert data["amount"] == "15000"
    assert data["currency"] == "Ar"
    assert data["descriptionText"] == "Commande 1 café"
    assert data["debitParty"] == [{"key": "msisdn", "value": "0343500003"}]
    assert data["creditParty"] == [{"key": "msisdn", "value": "0343500004"}]
    assert data["requestingOrganisationTransactionReference"] == "CMD-1"
    assert data["requestDate"].endswith("Z")


def test_token_is_cached(api, mvola):
    api.add("POST", PAY, {"status": "pending", "serverCorrelationId": "c"})
    mvola.initiate_payment(amount=100, phone="0343500003", reference="A")
    mvola.initiate_payment(amount=100, phone="0343500003", reference="B")
    assert api.count("/token") == 1


@pytest.mark.parametrize(
    "remote, expected",
    [
        ("pending", PaymentStatus.PENDING),
        ("completed", PaymentStatus.SUCCESS),
        ("failed", PaymentStatus.FAILED),
        ("weird", PaymentStatus.UNKNOWN),
    ],
)
def test_get_status_maps_values(api, mvola, remote, expected):
    api.add("POST", PAY, {"status": "pending", "serverCorrelationId": "corr-9"})
    api.add("GET", PAY + "status/corr-9", {"status": remote, "objectReference": "6362512"})
    payment = mvola.initiate_payment(amount=100, phone="0343500003", reference="X")
    payment = mvola.get_status(payment)
    assert payment.status is expected
    assert payment.transaction_id == "6362512"
    assert "X-Callback-URL" not in api.last("GET", "status/").headers


def test_get_transaction(api, mvola):
    api.add("GET", PAY + "636251282", {"amount": "5555.00", "transactionStatus": "completed"})
    assert mvola.get_transaction("636251282")["transactionStatus"] == "completed"


def test_auth_failure_clears_token(api, mvola):
    api.add("POST", PAY, httpx.Response(401, json={"fault": {"code": 900901}}))
    with pytest.raises(AuthenticationError):
        mvola.initiate_payment(amount=100, phone="0343500003", reference="X")
    assert mvola._token is None


def test_http_error_raises_provider_error(api, mvola):
    api.add("POST", PAY, httpx.Response(400, json={"errorDescription": "bad"}))
    with pytest.raises(ProviderError) as exc:
        mvola.initiate_payment(amount=100, phone="0343500003", reference="X")
    assert exc.value.status_code == 400
    assert exc.value.payload == {"errorDescription": "bad"}


def test_validation():
    with pytest.raises(ConfigurationError):
        MVola(consumer_key="", consumer_secret="s", merchant_number="0343500004", partner_name="x")
    with pytest.raises(ConfigurationError):
        MVola(consumer_key="k", consumer_secret="s", merchant_number="0343500004", partner_name="")
    with pytest.raises(ConfigurationError):
        MVola(
            consumer_key="k",
            consumer_secret="s",
            merchant_number="0343500004",
            partner_name="x",
            language="EN",
        )


def test_initiate_requires_phone_and_positive_int(mvola):
    with pytest.raises(ValueError):
        mvola.initiate_payment(amount=100, reference="X")
    with pytest.raises(ValueError):
        mvola.initiate_payment(amount=0, phone="0343500003", reference="X")
    with pytest.raises(ValueError):
        mvola.initiate_payment(amount=10.5, phone="0343500003", reference="X")  # type: ignore[arg-type]


def test_parse_webhook():
    mvola = MVola(consumer_key="k", consumer_secret="s", merchant_number="0343500004", partner_name="x")
    event = mvola.parse_webhook(
        json.dumps(
            {
                "transactionStatus": "completed",
                "serverCorrelationId": "corr-1",
                "transactionReference": "641235",
            }
        ).encode()
    )
    assert event.status is PaymentStatus.SUCCESS
    assert event.provider_id == "corr-1"
    assert event.transaction_id == "641235"
    with pytest.raises(WebhookError):
        mvola.parse_webhook({"foo": "bar"})


def test_clean_description():
    assert clean_description("Facture n°12 / juin!!") == "Facture n 12 juin"
    assert len(clean_description("x" * 100)) == 40
    assert clean_description("!!!") == "Paiement"
