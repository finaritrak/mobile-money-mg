import pytest

from mobile_money_mg import (
    AirtelMoney,
    ConfigurationError,
    MobileMoney,
    MVola,
    Operator,
    PaymentStatus,
    ProviderError,
    Simulator,
    UnsupportedOperator,
    WebhookError,
)


def test_sandbox_success_flow():
    mm = MobileMoney.sandbox()
    payment = mm.pay(amount=15000, phone="0341234567", reference="CMD-1")
    assert payment.status is PaymentStatus.PENDING
    assert payment.operator is Operator.SIMULATOR
    payment = mm.status(payment)
    assert payment.is_paid
    assert payment.transaction_id.startswith("SIM")


@pytest.mark.parametrize(
    "phone, expected",
    [
        ("0341234513", PaymentStatus.FAILED),
        ("0321234598", PaymentStatus.EXPIRED),
        ("0331234599", PaymentStatus.PENDING),
    ],
)
def test_sandbox_outcomes(phone, expected):
    mm = MobileMoney.sandbox()
    payment = mm.status(mm.pay(amount=100, phone=phone, reference="R"))
    assert payment.status is expected


def test_simulator_duplicate_and_unknown():
    mm = MobileMoney.sandbox()
    mm.pay(amount=100, phone="0341234567", reference="R")
    with pytest.raises(ProviderError):
        mm.pay(amount=100, phone="0341234567", reference="R")
    sim = Simulator()
    other = MobileMoney.sandbox().pay(amount=1, phone="0341234567", reference="Z")
    with pytest.raises(ProviderError):
        sim.get_status(other)


def test_wait_polls_until_final_with_backoff():
    mm = MobileMoney.sandbox()
    payment = mm.pay(amount=100, phone="0341234599", reference="R")
    sleeps = []
    now = [0.0]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    result = mm.wait(payment, timeout=30, interval=4, sleep=fake_sleep, clock=lambda: now[0])
    assert result.status is PaymentStatus.PENDING  # …99 never completes
    assert sleeps[:3] == [4, 6, 9]
    assert sum(sleeps) == pytest.approx(30)


def test_wait_returns_immediately_when_final():
    mm = MobileMoney.sandbox()
    payment = mm.pay(amount=100, phone="0341234567", reference="R")
    assert mm.wait(payment, sleep=lambda s: pytest.fail("should not sleep")).is_paid


def test_webhook_roundtrip_with_confirmation():
    sim = Simulator()
    mm = MobileMoney(simulator=sim)
    payment = mm.pay(amount=100, phone="0341234567", reference="R")
    payload = sim.webhook_payload(payment)
    confirmed = mm.confirm_webhook(payment, payload)
    assert confirmed.is_paid

    with pytest.raises(WebhookError):
        mm.confirm_webhook(payment, {**payload, "reference": "OTHER", "provider_id": "x"})
    with pytest.raises(WebhookError):
        mm.parse_webhook(Operator.SIMULATOR, {"status": "nope"})


def test_routing_by_prefix(api):
    api.add("POST", "https://openapiuat.airtel.africa/auth/oauth2/token", {"access_token": "t"})
    api.add(
        "POST",
        "https://openapiuat.airtel.africa/merchant/v1/payments/",
        {"data": {"transaction": {"id": "R"}}, "status": {"success": True}},
    )
    mm = MobileMoney(airtel=AirtelMoney(client_id="a", client_secret="b", http_client=api.client()))
    assert mm.operators == [Operator.AIRTEL_MONEY]
    assert mm.pay(amount=100, phone="0331234567", reference="R").operator is Operator.AIRTEL_MONEY
    with pytest.raises(UnsupportedOperator):
        mm.pay(amount=100, phone="0341234567", reference="R2")  # MVola not configured
    with pytest.raises(UnsupportedOperator):
        mm.pay(amount=100, phone="0391234567", reference="R3")  # unknown prefix
    with pytest.raises(ValueError):
        mm.pay(amount=100, reference="R4")


def test_explicit_operator_overrides_prefix():
    mm = MobileMoney(
        mvola=MVola(consumer_key="k", consumer_secret="s", merchant_number="0343500004", partner_name="x")
    )
    assert mm.provider("mvola").operator is Operator.MVOLA
    with pytest.raises(UnsupportedOperator):
        mm.pay(amount=1, phone="0341234567", reference="R", operator="orange_money")
    mm.close()


def test_requires_a_provider():
    with pytest.raises(ConfigurationError):
        MobileMoney()


def test_from_env():
    assert MobileMoney.from_env({"MOBILE_MONEY_SIMULATOR": "1"}).operators == [Operator.SIMULATOR]
    env = {
        "MVOLA_CONSUMER_KEY": "k",
        "MVOLA_CONSUMER_SECRET": "s",
        "MVOLA_MERCHANT_NUMBER": "0343500004",
        "MVOLA_PARTNER_NAME": "Shop",
        "ORANGE_MERCHANT_KEY": "mk",
        "ORANGE_AUTHORIZATION_HEADER": "Basic x",
        "ORANGE_RETURN_URL": "https://a",
        "ORANGE_CANCEL_URL": "https://b",
        "ORANGE_NOTIF_URL": "https://c",
        "AIRTEL_CLIENT_ID": "a",
        "AIRTEL_CLIENT_SECRET": "b",
        "MOBILE_MONEY_PRODUCTION": "true",
    }
    with MobileMoney.from_env(env) as mm:
        assert set(mm.operators) == {Operator.MVOLA, Operator.ORANGE_MONEY, Operator.AIRTEL_MONEY}
        assert mm.provider(Operator.MVOLA).base_url == "https://api.mvola.mg"
    with pytest.raises(ConfigurationError, match="MVOLA_CONSUMER_SECRET"):
        MobileMoney.from_env({"MVOLA_CONSUMER_KEY": "k"})
