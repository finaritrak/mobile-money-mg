import httpx
import pytest

from mobile_money_mg import AuthenticationError, MVola, WebhookError
from mobile_money_mg._utils import load_body


def test_load_body_variants():
    assert load_body({"a": 1}) == {"a": 1}
    assert load_body(b'{"a": 1}') == {"a": 1}
    assert load_body("status=SUCCESS&txnid=MP1") == {"status": "SUCCESS", "txnid": "MP1"}


@pytest.mark.parametrize("raw", ["", "   ", "{not json", "[1, 2]", 42, "nokeyvalue"])
def test_load_body_errors(raw):
    with pytest.raises(WebhookError):
        load_body(raw)


def test_token_without_access_token_raises(api):
    api.add("POST", "https://devapi.mvola.mg/token", {"error": "nope"})
    mvola = MVola(
        consumer_key="k",
        consumer_secret="s",
        merchant_number="0343500004",
        partner_name="x",
        http_client=api.client(),
    )
    with pytest.raises(AuthenticationError):
        mvola.initiate_payment(amount=1, phone="0343500003", reference="R")


def test_bad_expires_in_and_non_json_errors(api):
    api.add("POST", "https://devapi.mvola.mg/token", {"access_token": "t", "expires_in": "soon"})
    api.add(
        "POST",
        "https://devapi.mvola.mg/mvola/mm/transactions/type/merchantpay/1.0.0/",
        httpx.Response(502, text="Bad gateway"),
    )
    with MVola(
        consumer_key="k",
        consumer_secret="s",
        merchant_number="0343500004",
        partner_name="x",
        http_client=api.client(),
    ) as mvola:
        with pytest.raises(Exception) as exc:
            mvola.initiate_payment(amount=1, phone="0343500003", reference="R")
        assert exc.value.payload == {"text": "Bad gateway"}
        assert mvola._token == "t"


def test_owned_client_is_closed():
    mvola = MVola(consumer_key="k", consumer_secret="s", merchant_number="0343500004", partner_name="x")
    mvola.close()
    assert mvola._http.is_closed
