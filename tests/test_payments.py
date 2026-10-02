import json
from io import StringIO
from unittest.mock import patch

import httpx
import pytest
from django.contrib import admin
from django.core.management import CommandError, call_command
from django.urls import reverse

import django_bale_payments
from django_bale_payments.admin import BalePaymentAdmin, PaymentAdmin
from django_bale_payments.checks import check_bale_settings
from django_bale_payments.client import BaleClient
from django_bale_payments.conf import BaleSettings
from django_bale_payments.exceptions import PreCheckoutRejected
from django_bale_payments.models import BalePayment, Currency, Payment
from django_bale_payments.services import BalePayService, UpdateKind, get_service
from django_bale_payments.signals import bale_pre_checkout


def payload_for(payment):
    return get_service().create_payload(payment)


class FakeClient:
    def __init__(self):
        self.invoice = None
        self.answers = []
        self.bot_username = "FakeBot"

    def send_invoice(self, **payload):
        self.invoice = payload
        return {"message_id": 7}

    def answer_pre_checkout_query(self, query_id, ok, error_message=None):
        self.answers.append((query_id, ok, error_message))


@pytest.mark.django_db
def test_create_invoice_uses_signed_payload():
    client = FakeClient()
    payment, message = BalePayService(client=client).create_invoice(
        chat_id=1,
        reference="order:42",
        title="Plan",
        description="A plan",
        amount=500_000,
    )
    assert message == {"message_id": 7}
    assert payment.title == "Plan"
    assert payment.description == "A plan"
    assert payment.chat_id == "1"
    assert client.invoice["payload"] == payload_for(payment)
    assert client.invoice["prices"] == [{"label": "Plan", "amount": 500_000}]


@pytest.mark.django_db
def test_successful_payment_is_idempotent():
    payment = BalePayment.objects.create(
        reference="order:42",
        amount=500_000,
        title="Plan",
        description="A plan",
    )
    assert payment.is_pending is True
    assert payment.is_paid is False

    update = {
        "invoice_payload": payload_for(payment),
        "payment_charge_id": "charge-1",
        "currency": "IRR",
        "total_amount": 500_000,
    }
    service = get_service()
    paid, created = service.record_successful_payment(update)
    again, repeated = service.record_successful_payment(update)
    assert paid.status == BalePayment.Status.PAID
    assert paid.is_paid is True
    assert created is True
    assert again.pk == paid.pk
    assert repeated is False
    assert "order:42" in str(paid)


@pytest.mark.django_db
def test_pre_checkout_rejects_modified_total():
    payment = BalePayment.objects.create(
        reference="order:42",
        amount=500_000,
        title="Plan",
    )
    with pytest.raises(Exception, match="does not match"):
        get_service().approve_pre_checkout(
            {
                "invoice_payload": payload_for(payment),
                "currency": "IRR",
                "total_amount": 1,
            }
        )


@pytest.mark.django_db
def test_pre_checkout_rejects_modified_currency():
    payment = BalePayment.objects.create(
        reference="order:currency",
        amount=500_000,
        title="Currency test",
    )
    with pytest.raises(Exception, match="does not match"):
        get_service().approve_pre_checkout(
            {
                "invoice_payload": payload_for(payment),
                "currency": "IRT",
                "total_amount": 500_000,
            }
        )


def test_payment_admin_registered():
    assert BalePayment in admin.site._registry
    assert isinstance(admin.site._registry[BalePayment], BalePaymentAdmin)
    assert PaymentAdmin is BalePaymentAdmin


def test_system_checks_pass():
    errors = check_bale_settings()
    assert errors == []


def test_system_checks_invalid_bot_username():
    with patch("django.conf.settings.BALE_PAYMENTS", {
        "BOT_TOKEN": "tok",
        "PROVIDER_TOKEN": "prov",
        "WEBHOOK_SECRET": "sec",
        "BOT_USERNAME": 12345,
    }):
        errors = check_bale_settings()
        assert any(e.id == "django_bale_payments.E005" for e in errors)


def test_top_level_package_exports():
    assert hasattr(django_bale_payments, "BalePayment")
    assert hasattr(django_bale_payments, "Payment")
    assert hasattr(django_bale_payments, "Currency")
    assert django_bale_payments.Payment is django_bale_payments.BalePayment
    assert Payment is BalePayment
    assert hasattr(django_bale_payments, "BaleClient")
    assert hasattr(django_bale_payments, "get_client")
    assert hasattr(django_bale_payments, "BalePayService")
    assert hasattr(django_bale_payments, "get_service")
    assert hasattr(django_bale_payments, "UpdateKind")
    from django_bale_payments.enums import UpdateKind as EnumsUpdateKind
    assert django_bale_payments.UpdateKind is EnumsUpdateKind
    assert hasattr(django_bale_payments, "bale_payment_paid")
    assert hasattr(django_bale_payments, "bale_payment_failed")
    assert hasattr(django_bale_payments, "bale_pre_checkout")
    assert hasattr(django_bale_payments, "BaleAPIError")
    assert hasattr(django_bale_payments, "PreCheckoutRejected")
    assert hasattr(django_bale_payments, "__version__")


def test_client_webhook_methods():
    client = BaleClient(
        BaleSettings(
            bot_token="token",
            provider_token="provider",
            webhook_secret="secret123",
        )
    )

    with patch.object(client, "call", return_value={"ok": True}) as mock_call:
        client.set_webhook("https://example.com/webhook/")
        mock_call.assert_called_once_with(
            "setWebhook",
            {
                "url": "https://example.com/webhook/",
                "secret_token": "secret123",
            },
        )

    with patch.object(client, "call", return_value={"url": "https://example.com/webhook/"}) as mock_call:
        info = client.get_webhook_info()
        assert info["url"] == "https://example.com/webhook/"
        mock_call.assert_called_once_with("getWebhookInfo", {})

    with patch.object(client, "call", return_value=True) as mock_call:
        client.delete_webhook()
        mock_call.assert_called_once_with("deleteWebhook", {})


    with patch.object(client, "call", return_value=[{"update_id": 1}]) as mock_call:
        updates = client.get_updates(offset=5, timeout=10)
        assert len(updates) == 1
        mock_call.assert_called_once_with(
            "getUpdates",
            {"offset": 5, "limit": 100, "timeout": 10},
            timeout=20,
        )


def test_bale_set_webhook_command():
    out = StringIO()
    with patch.object(BaleClient, "call", return_value=True) as mock_call:
        call_command("bale_set_webhook", "https://example.com", stdout=out)
    assert "Successfully registered webhook" in out.getvalue()
    expected_url = "https://example.com" + reverse("django_bale_payments:webhook")
    mock_call.assert_called_once_with(
        "setWebhook", {"url": expected_url, "secret_token": "webhook-secret"}
    )


def test_bale_set_webhook_command_uses_settings_base_url():
    out = StringIO()
    config = {
        "BOT_TOKEN": "tok",
        "PROVIDER_TOKEN": "prov",
        "WEBHOOK_SECRET": "sec",
        "WEBHOOK_BASE_URL": "https://settings.example.com/",
    }
    with (
        patch("django.conf.settings.BALE_PAYMENTS", config),
        patch.object(BaleClient, "call", return_value=True) as mock_call,
    ):
        call_command("bale_set_webhook", stdout=out)
    expected_url = "https://settings.example.com" + reverse("django_bale_payments:webhook")
    mock_call.assert_called_once_with("setWebhook", {"url": expected_url, "secret_token": "sec"})


def test_bale_set_webhook_command_accepts_full_webhook_url():
    out = StringIO()
    full_url = "https://example.com" + reverse("django_bale_payments:webhook")
    with patch.object(BaleClient, "call", return_value=True) as mock_call:
        call_command("bale_set_webhook", full_url, stdout=out)
    assert "Successfully registered webhook" in out.getvalue()
    mock_call.assert_called_once_with(
        "setWebhook", {"url": full_url, "secret_token": "webhook-secret"}
    )

    # Also test passing full URL without trailing slash
    out2 = StringIO()
    with patch.object(BaleClient, "call", return_value=True) as mock_call2:
        call_command("bale_set_webhook", full_url.rstrip("/"), stdout=out2)
    assert "Successfully registered webhook" in out2.getvalue()
    mock_call2.assert_called_once_with(
        "setWebhook", {"url": full_url, "secret_token": "webhook-secret"}
    )


def test_bale_set_webhook_command_raises_without_url():
    with pytest.raises(CommandError):
        call_command("bale_set_webhook")


def test_bale_webhook_info_command():
    out = StringIO()
    with patch.object(
        BaleClient,
        "call",
        return_value={"url": "https://example.com/webhook/", "pending_update_count": 0},
    ):
        call_command("bale_webhook_info", stdout=out)
    assert "Active Webhook URL: https://example.com/webhook/" in out.getvalue()

    delete_out = StringIO()
    with patch.object(BaleClient, "call", return_value=True):
        call_command("bale_webhook_info", "--delete", stdout=delete_out)
    assert "Successfully deleted webhook from Bale." in delete_out.getvalue()


@pytest.mark.django_db
def test_bale_poll_command():
    out = StringIO()
    call_count = 0
    service = get_service()
    payment, _ = service.initialize_payment(
        reference="order:poll_test",
        amount=100_000,
        title="Test item",
        description="Test description",
    )

    def mock_get_updates(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [
                {
                    "update_id": 100,
                    "message": {
                        "chat": {"id": 12345},
                        "text": f"/start pay_{payment.id.hex}",
                    },
                }
            ]
        raise KeyboardInterrupt

    with (
        patch.object(BaleClient, "get_webhook_info", return_value={"url": ""}),
        patch.object(BaleClient, "get_updates", side_effect=mock_get_updates),
        patch.object(BaleClient, "send_invoice", return_value={"message_id": 42}),
    ):
        call_command("bale_poll", stdout=out)

    output = out.getvalue()
    assert "Bale Payments Development Polling Worker" in output
    assert "[INVOICE SENT] Ref: order:poll_test" in output
    assert "Amount: 100000 IRR" in output
    assert "Polling worker stopped." in output


@pytest.mark.django_db
def test_initialize_payment_creates_deep_link():
    service = get_service()
    payment, pay_url = service.initialize_payment(
        reference="order:web_100",
        amount=300_000,
        title="Premium Access",
        description="30 days",
    )
    assert payment.status == BalePayment.Status.PENDING
    assert payment.amount == 300_000
    assert payment.title == "Premium Access"
    assert payment.description == "30 days"
    assert payment.metadata == {}
    expected_url = f"https://ble.ir/TestStoreBot?start=pay_{payment.id.hex}"
    assert pay_url == expected_url

    # Test custom developer metadata:
    p_meta, _ = service.initialize_payment(
        reference="order:web_meta",
        amount=100_000,
        title="Custom",
        description="With Meta",
        metadata={"user_id": 99, "plan": "pro"},
    )
    assert p_meta.metadata == {"user_id": 99, "plan": "pro"}

    # Test positional arguments and string amount:
    p2, url2 = service.initialize_payment("order:web_pos", "500000", "Positional", "Desc")
    assert p2.amount == 500_000
    assert p2.title == "Positional"
    assert p2.description == "Desc"
    assert url2 == f"https://ble.ir/TestStoreBot?start=pay_{p2.id.hex}"

    # Test custom client with explicit bot_username:
    fake = FakeClient()
    fake.bot_username = "AutoResolvedBot"
    p3, url3 = BalePayService(client=fake).initialize_payment(
        reference="order:web_auto",
        amount=250_000,
        title="Auto",
        description="Auto desc",
    )
    assert url3 == f"https://ble.ir/AutoResolvedBot?start=pay_{p3.id.hex}"

    # Test dynamic resolution via getMe when BOT_USERNAME is not in config:
    dynamic_client = BaleClient(BaleSettings(bot_token="tok", provider_token="prov"))
    with patch.object(dynamic_client, "call", return_value={"username": "DynamicBot"}):
        p4, url4 = BalePayService(client=dynamic_client).initialize_payment(
            "order:web_dyn",
            100_000,
            "Dyn",
            "Dyn",
        )
        assert url4 == f"https://ble.ir/DynamicBot?start=pay_{p4.id.hex}"

    # Test failure when username cannot be determined:
    bad_client = BaleClient(BaleSettings(bot_token="tok", provider_token="prov"))
    with patch.object(bad_client, "call", return_value={}):
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured, match="BOT_USERNAME"):
            BalePayService(client=bad_client).initialize_payment("order:fail", 10_000, "F", "F")


@pytest.mark.django_db
def test_currency_toman_conversion():
    service = get_service()

    # 1. Initialize with Currency.IRT enum
    p1, _ = service.initialize_payment(
        reference="order:toman_enum",
        amount=50_000,
        title="Toman Product",
        description="Priced in Toman",
        currency=Currency.IRT,
    )
    assert p1.currency == Currency.IRT
    assert p1.amount == 500_000  # 50,000 * 10
    assert p1.amount_in_toman == 50_000

    # 2. Initialize with string "irt" (case-insensitive)
    p2, _ = service.initialize_payment(
        reference="order:toman_str",
        amount="35000",
        title="Toman Str",
        description="Desc",
        currency="irt",
    )
    assert p2.currency == Currency.IRT
    assert p2.amount == 350_000
    assert p2.amount_in_toman == 35_000

    # 3. Create invoice with Currency.IRT
    client = FakeClient()
    p3, _ = BalePayService(client=client).create_invoice(
        chat_id=12345,
        reference="order:chat_toman",
        title="Chat Toman",
        description="Desc",
        amount=20_000,
        currency="toman",
    )
    assert p3.currency == Currency.IRT
    assert p3.amount == 200_000
    assert p3.amount_in_toman == 20_000
    assert client.invoice["prices"] == [{"label": "Chat Toman", "amount": 200_000}]
    assert client.invoice["currency"] == "IRR"

    # 4. Default is IRR without multiplication
    p4, _ = service.initialize_payment(
        reference="order:default_irr",
        amount=100_000,
        title="Rial",
        description="Desc",
    )
    assert p4.currency == Currency.IRR
    assert p4.amount == 100_000
    assert p4.amount_in_toman == 10_000


@pytest.mark.django_db
def test_process_update_handles_start_deep_link():
    client = FakeClient()
    client.bot_username = "CourseBot"
    service = BalePayService(client=client)
    payment, _ = service.initialize_payment(
        reference="order:web_101",
        amount=400_000,
        title="Course",
        description="Online Course",
    )

    update = {
        "update_id": 50,
        "message": {
            "chat": {"id": 777888},
            "text": f"/start pay_{payment.id.hex}",
        },
    }

    result = service.process_update(update)
    assert result.kind == UpdateKind.INVOICE_SENT
    assert result.payment.pk == payment.pk
    assert result.payment.chat_id == "777888"
    assert client.invoice["chat_id"] == 777888
    assert client.invoice["payload"] == payload_for(payment)
    assert client.invoice["prices"] == [{"label": "Course", "amount": 400_000}]


@pytest.mark.django_db
def test_process_update_pre_checkout_signal_approved():
    client = FakeClient()
    service = BalePayService(client=client)
    payment, _ = service.initialize_payment(
        reference="order:precheck_ok",
        amount=100_000,
        title="Widget",
        description="A widget",
    )

    signal_received = []

    def on_pre_checkout(sender, payment, query, **kwargs):
        signal_received.append((payment.reference, query["id"]))

    bale_pre_checkout.connect(on_pre_checkout)
    try:
        update = {
            "update_id": 99,
            "pre_checkout_query": {
                "id": "query_test_123",
                "invoice_payload": payload_for(payment),
                "currency": "IRR",
                "total_amount": 100_000,
            },
        }
        result = service.process_update(update)
        assert result.kind == UpdateKind.PRE_CHECKOUT_APPROVED
        assert result.payment.pk == payment.pk
        assert len(signal_received) == 1
        assert signal_received[0] == ("order:precheck_ok", "query_test_123")
        assert ("query_test_123", True, None) in client.answers
    finally:
        bale_pre_checkout.disconnect(on_pre_checkout)


@pytest.mark.django_db
def test_process_update_pre_checkout_signal_rejected():
    client = FakeClient()
    service = BalePayService(client=client)
    payment, _ = service.initialize_payment(
        reference="order:out_of_stock",
        amount=150_000,
        title="Rare Book",
        description="Only 1 left",
    )

    def on_pre_checkout(sender, payment, query, **kwargs):
        if payment.reference == "order:out_of_stock":
            raise PreCheckoutRejected("Sorry, item is out of stock!")

    bale_pre_checkout.connect(on_pre_checkout)
    try:
        update = {
            "update_id": 100,
            "pre_checkout_query": {
                "id": "query_test_456",
                "invoice_payload": payload_for(payment),
                "currency": "IRR",
                "total_amount": 150_000,
            },
        }
        result = service.process_update(update)
        assert result.kind == UpdateKind.PRE_CHECKOUT_REJECTED
        assert result.payment.pk == payment.pk
        assert ("query_test_456", False, "Sorry, item is out of stock!") in client.answers
    finally:
        bale_pre_checkout.disconnect(on_pre_checkout)


def test_client_get_me():
    client = BaleClient(
        BaleSettings(
            bot_token="token",
            provider_token="provider",
            webhook_secret="secret123",
        )
    )
    with patch.object(client, "call", return_value={"id": 1, "username": "Botty"}) as mock_call:
        res1 = client.get_me()
        res2 = client.get_me()
        assert res1["username"] == "Botty"
        assert res2["username"] == "Botty"
        assert client.bot_username == "Botty"
        mock_call.assert_called_once_with("getMe", {})


def test_client_send_invoice_explicit_args():
    client = BaleClient(
        BaleSettings(
            bot_token="token",
            provider_token="default_provider_token",
        )
    )
    with patch.object(client, "call", return_value={"message_id": 123}) as mock_call:
        client.send_invoice(
            chat_id=999,
            title="Book",
            description="A nice book",
            payload="secret_payload",
            prices=[{"label": "Book", "amount": 1000}],
            photo_url="https://example.com/cover.jpg",
        )
        mock_call.assert_called_once_with(
            "sendInvoice",
            {
                "chat_id": 999,
                "title": "Book",
                "description": "A nice book",
                "payload": "secret_payload",
                "provider_token": "default_provider_token",
                "currency": "IRR",
                "prices": [{"label": "Book", "amount": 1000}],
                "photo_url": "https://example.com/cover.jpg",
            },
        )


def test_client_send_message_and_pre_checkout():
    client = BaleClient(
        BaleSettings(
            bot_token="token",
            provider_token="provider",
        )
    )
    with patch.object(client, "call", return_value=True) as mock_call:
        client.send_message(123, "Hello!")
        mock_call.assert_called_with("sendMessage", {"chat_id": 123, "text": "Hello!"})

    with patch.object(client, "call", return_value=True) as mock_call:
        client.answer_pre_checkout_query("query_123", ok=True)
        mock_call.assert_called_with(
            "answerPreCheckoutQuery",
            {"pre_checkout_query_id": "query_123", "ok": True},
        )

    with patch.object(client, "call", return_value=True) as mock_call:
        client.inquire_transaction("charge_123")
        mock_call.assert_called_with(
            "inquireTransaction",
            {"payment_charge_id": "charge_123"},
        )


def test_bale_client_httpx_mock_transport_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload == {"chat_id": 123, "text": "Hello"}
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = BaleClient(
        BaleSettings(bot_token="tok", provider_token="prov"),
        client=mock_client,
    )
    result = client.send_message(123, "Hello")
    assert result == {"message_id": 99}


def test_bale_client_httpx_mock_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "Chat not found"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = BaleClient(
        BaleSettings(bot_token="tok", provider_token="prov"),
        client=mock_client,
    )
    with pytest.raises(django_bale_payments.BaleAPIError, match="Chat not found"):
        client.send_message(123, "Hello")


def test_bale_client_context_manager():
    with BaleClient(BaleSettings(bot_token="tok", provider_token="prov")) as client:
        assert client._client.is_closed is False
    assert client._client.is_closed is True


def test_get_client_returns_singleton():
    c1 = django_bale_payments.get_client()
    c2 = django_bale_payments.get_client()
    assert c1 is c2
    assert isinstance(c1, BaleClient)


@pytest.mark.django_db
def test_bale_pay_service_singleton_and_custom_instance():
    s1 = django_bale_payments.get_service()
    s2 = django_bale_payments.get_service()
    assert s1 is s2
    assert isinstance(s1, django_bale_payments.BalePayService)

    fake_client = FakeClient()
    custom_service = django_bale_payments.BalePayService(client=fake_client)
    assert custom_service.client is fake_client

    payment, msg = custom_service.create_invoice(
        chat_id=123,
        reference="order:service_test",
        title="Test Title",
        description="Test Desc",
        amount=100_000,
    )
    assert payment.reference == "order:service_test"
    assert payment.title == "Test Title"
    assert payment.description == "Test Desc"
    assert payment.chat_id == "123"
    assert msg == {"message_id": 7}
    assert fake_client.invoice["chat_id"] == 123


@pytest.mark.django_db
def test_webhook_handles_already_paid_payment_gracefully(client):
    payment = BalePayment.objects.create(
        reference="order:admin_paid",
        amount=200_000,
        title="Admin Settled",
        status=BalePayment.Status.PAID,
    )
    assert payment.bale_charge_id is None

    signal_received = []

    def on_paid(sender, payment, **kwargs):
        signal_received.append(payment.pk)

    django_bale_payments.signals.bale_payment_paid.connect(on_paid)
    try:
        update = {
            "update_id": 999,
            "message": {
                "successful_payment": {
                    "invoice_payload": payload_for(payment),
                    "payment_charge_id": "bale-charge-later-123",
                    "currency": "IRR",
                    "total_amount": 200_000,
                }
            },
        }
        res = client.post(
            reverse("django_bale_payments:webhook"),
            data=json.dumps(update),
            content_type="application/json",
            HTTP_X_BALE_WEBHOOK_SECRET="webhook-secret",
        )
        assert res.status_code == 200
        assert res.json()["ok"] is True
        assert res.json()["kind"] == "successful_payment"

        payment.refresh_from_db()
        assert payment.bale_charge_id == "bale-charge-later-123"
        assert len(signal_received) == 0  # not emitted again
    finally:
        django_bale_payments.signals.bale_payment_paid.disconnect(on_paid)


@pytest.mark.django_db
def test_signal_exception_does_not_crash_webhook(client):
    payment = BalePayment.objects.create(
        reference="order:crash_signal",
        amount=150_000,
        title="Crash Test",
        status=BalePayment.Status.PENDING,
    )

    def failing_receiver(sender, payment, **kwargs):
        raise RuntimeError("SMS provider is down!")

    django_bale_payments.signals.bale_payment_paid.connect(failing_receiver)
    try:
        update = {
            "update_id": 1000,
            "message": {
                "successful_payment": {
                    "invoice_payload": payload_for(payment),
                    "payment_charge_id": "charge-safe-123",
                    "currency": "IRR",
                    "total_amount": 150_000,
                }
            },
        }
        res = client.post(
            reverse("django_bale_payments:webhook"),
            data=json.dumps(update),
            content_type="application/json",
            HTTP_X_BALE_WEBHOOK_SECRET="webhook-secret",
        )
        assert res.status_code == 200
        assert res.json()["ok"] is True

        payment.refresh_from_db()
        assert payment.is_paid is True
        assert payment.bale_charge_id == "charge-safe-123"
    finally:
        django_bale_payments.signals.bale_payment_paid.disconnect(failing_receiver)


@pytest.mark.django_db
def test_admin_mark_as_paid_action():
    from unittest.mock import MagicMock

    from django.contrib.admin.sites import AdminSite

    from django_bale_payments.admin import BalePaymentAdmin

    payment = BalePayment.objects.create(
        reference="order:admin_action",
        amount=100_000,
        title="Test Action",
        status=BalePayment.Status.PENDING,
    )

    site = AdminSite()
    admin_inst = BalePaymentAdmin(BalePayment, site)

    signal_received = []

    def on_paid(sender, payment, **kwargs):
        signal_received.append(payment.pk)

    django_bale_payments.signals.bale_payment_paid.connect(on_paid)
    try:
        req = MagicMock()
        admin_inst.mark_as_paid(req, BalePayment.objects.filter(pk=payment.pk))

        payment.refresh_from_db()
        assert payment.status == BalePayment.Status.PAID
        assert payment.paid_at is not None
        assert len(signal_received) == 1
    finally:
        django_bale_payments.signals.bale_payment_paid.disconnect(on_paid)

