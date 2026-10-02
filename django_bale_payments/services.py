import hashlib
import hmac
import logging
import uuid
from typing import Any, NamedTuple

from django.db import IntegrityError, transaction
from django.utils import timezone

from .client import BaleClient, get_client
from .conf import BaleSettings, get_settings
from .enums import UpdateKind
from .exceptions import InvalidPaymentUpdate, PreCheckoutRejected
from .models import BalePayment, Currency
from .signals import bale_invoice_sent, bale_payment_failed, bale_payment_paid, bale_pre_checkout

logger = logging.getLogger(__name__)

START_COMMAND = "/start pay_"


class UpdateResult(NamedTuple):
    kind: UpdateKind
    payment: BalePayment | None


def _clean_amount(amount: int | str) -> int:
    try:
        value = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"amount must be an integer, got {amount!r}") from exc
    if value <= 0:
        raise ValueError("amount must be a positive integer")
    return value


class BalePayService:
    """Creates Bale invoices and processes the payment updates Bale sends back."""

    def __init__(self, client: BaleClient | None = None, config: BaleSettings | None = None) -> None:
        self.client = client or get_client()
        self.config = config or get_settings()

    def get_signature(self, payment_id: str) -> str:
        """First 24 hex digits of HMAC-SHA256 of payment ID to prevent forgery."""
        secret = self.config.webhook_secret
        if not secret:
            raise ValueError("Bale webhook secret is not configured.")

        # Truncaing to 24 hex digits (12 bytes) is enough to prevent forgery (2^96), and keeps the payload short.
        return hmac.new(secret.encode(), payment_id.encode(), hashlib.sha256).hexdigest()[:24]

    def create_payload(self, payment: BalePayment) -> str:
        """Create a payload for a Bale invoice that can be verified later.
        format: "bale:<payment_id>:<signature>".
        """
        return f"bale:{payment.pk}:{self.get_signature(str(payment.pk))}"

    def parse_payload(self, payload: str) -> BalePayment:
        """Resolve a payload created by create_payload back to its BalePayment object."""
        try:
            prefix, payment_id, signature = payload.split(":", 2)
        except ValueError:
            raise InvalidPaymentUpdate("Malformed payment payload") from None

        if prefix != "bale" or not hmac.compare_digest(signature, self.get_signature(payment_id)):
            raise InvalidPaymentUpdate("Invalid payment payload signature")

        try:
            return BalePayment.objects.get(pk=payment_id)
        except BalePayment.DoesNotExist:
            raise InvalidPaymentUpdate("Unknown payment payload") from None

    def _create_payment(
        self,
        reference: str,
        amount: int | str,
        title: str,
        description: str,
        *,
        chat_id: int | str | None = None,
        currency: Currency | str = Currency.IRR,
        metadata: dict[str, Any] | None = None,
    ) -> BalePayment:
        selected_currency = Currency.IRT if str(currency).upper() in ("IRT", "TOMAN") else Currency.IRR
        numeric_amount = _clean_amount(amount)
        if selected_currency == Currency.IRT:
            numeric_amount *= 10

        return BalePayment.objects.create(
            reference=reference,
            amount=numeric_amount,
            currency=selected_currency,
            title=title,
            description=description,
            chat_id=str(chat_id) if chat_id is not None else None,
            metadata=dict(metadata or {}),
        )

    def initialize_payment(
        self,
        reference: str,
        amount: int | str,
        title: str,
        description: str,
        *,
        currency: Currency | str = Currency.IRR,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[BalePayment, str]:
        """Create a pending payment for web checkout and return its object and Bale deep link.

        When the customer opens the link and sends /start, the service automatically
        sends the invoice to their chat, and once paid, emits `bale_payment_paid`.

        Args:
            reference: Your order/invoice identifier (e.g. 'order:1024').
            amount: Payment amount (positive integer or numeric string).
            title: Product or service title shown on the invoice card message.
            description: Description shown on the invoice card.
            currency: Currency ('IRR' or 'IRT').
            metadata: Optional dict of custom data stored on the payment.

        Returns:
            tuple[BalePayment, str]: A tuple containing:
                - BalePayment: The created or retrieved payment instance.
                - str: The deep link URL to open the payment in Bale
                (format: ``https://ble.ir/<bot_username>?start=pay_<payment_id>``).
        """
        payment = self._create_payment(
            reference=reference,
            amount=amount,
            title=title,
            description=description,
            currency=currency,
            metadata=metadata,
        )
        link = f"https://ble.ir/{self.client.bot_username}?start=pay_{payment.id.hex}"
        logger.info("Initialized payment %s (ref %s), deep link: %s", payment.pk, reference, link)
        return payment, link

    def send_invoice(self, chat_id: int | str, payment: BalePayment) -> Any:
        """Send invoice to chat, link chat_id and message metadata, and emit bale_invoice_sent."""
        logger.info("Sending Bale invoice for %s to chat %s", payment.pk, chat_id)
        message = self.client.send_invoice(
            chat_id=chat_id,
            title=payment.title,
            description=payment.description or "Payment invoice",
            payload=self.create_payload(payment),
            provider_token=self.config.provider_token,
            currency="IRR",
            prices=[{"label": payment.title, "amount": payment.amount}],
        )
        payment.chat_id = str(chat_id)
        if isinstance(message, dict):
            payment.metadata["bale_message"] = message
        payment.save(update_fields=["chat_id", "metadata"])
        bale_invoice_sent.send(sender=BalePayment, payment=payment, chat_id=chat_id)
        return message

    def create_invoice(
        self,
        chat_id: int | str,
        reference: str,
        title: str,
        description: str,
        amount: int | str,
        *,
        currency: Currency | str = Currency.IRR,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[BalePayment, Any]:
        """Create a pending payment and immediately send its invoice to a Bale chat."""
        payment = self._create_payment(
            reference=reference,
            amount=amount,
            title=title,
            description=description,
            chat_id=chat_id,
            currency=currency,
            metadata=metadata,
        )
        message = self.send_invoice(chat_id, payment)
        return payment, message

    def handle_start_payment(self, *, token: str, chat_id: int | str) -> BalePayment | None:
        """Answer a deep-link start ('pay_<hex>') by sending the invoice if pending."""
        try:
            payment = BalePayment.objects.get(pk=uuid.UUID(hex=token))
        except (ValueError, BalePayment.DoesNotExist):
            logger.warning("Start token %s matched no payment", token)
            return None

        if not payment.is_pending:
            logger.info("Payment %s is %s, ignoring start token", payment.pk, payment.status)
            return None

        self.send_invoice(chat_id, payment)
        return payment

    def approve_pre_checkout(self, query: dict[str, Any]) -> BalePayment:
        """Validate pre-checkout query payload and amount; raises InvalidPaymentUpdate on mismatch."""
        payment = self.parse_payload(query.get("invoice_payload", ""))
        if not payment.is_pending:
            raise InvalidPaymentUpdate("This payment is no longer available")
        self._check_charge(payment, query)
        return payment

    def record_successful_payment(self, successful_payment: dict[str, Any]) -> tuple[BalePayment, bool]:
        """Mark payment paid atomically; returns (payment, first_time_paid)."""
        payment = self.parse_payload(successful_payment.get("invoice_payload", ""))
        charge_id = successful_payment.get("payment_charge_id") or successful_payment.get(
            "telegram_payment_charge_id"
        )
        if not charge_id:
            raise InvalidPaymentUpdate("Missing payment charge ID")
        self._check_charge(payment, successful_payment)

        try:
            with transaction.atomic():
                payment = BalePayment.objects.select_for_update().get(pk=payment.pk)
                if payment.is_paid:
                    if not payment.bale_charge_id:
                        payment.bale_charge_id = charge_id
                        payment.save(update_fields=["bale_charge_id", "updated_at"])
                    elif payment.bale_charge_id != charge_id:
                        logger.warning(
                            "Payment %s is already paid with charge %s; received charge %s",
                            payment.pk,
                            payment.bale_charge_id,
                            charge_id,
                        )
                    return payment, False

                payment.status = BalePayment.Status.PAID
                payment.bale_charge_id = charge_id
                payment.paid_at = timezone.now()
                payment.save(update_fields=["status", "bale_charge_id", "paid_at", "updated_at"])
        except IntegrityError as exc:
            raise InvalidPaymentUpdate("Payment charge is already assigned") from exc

        logger.info("Payment %s paid with charge %s", payment.pk, charge_id)
        responses = bale_payment_paid.send_robust(sender=BalePayment, payment=payment)
        for receiver, response in responses:
            if isinstance(response, Exception):
                logger.error(
                    "Error executing signal receiver %s for payment %s: %s",
                    receiver,
                    payment.pk,
                    response,
                    exc_info=response,
                )
        return payment, True

    @staticmethod
    def _check_charge(payment: BalePayment, charge: dict[str, Any]) -> None:
        if charge.get("currency") != "IRR" or charge.get("total_amount") != payment.amount:
            raise InvalidPaymentUpdate("Charge total or currency does not match the payment")

    def process_update(self, update: dict[str, Any]) -> UpdateResult:
        """Route raw Bale update (pre_checkout_query, /start deep link, or successful_payment)."""
        if query := update.get("pre_checkout_query"):
            return self._handle_pre_checkout(query)

        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        if text.startswith(START_COMMAND):
            token = text.removeprefix(START_COMMAND).strip()
            chat_id = (message.get("chat") or {}).get("id")
            if token and chat_id and (payment := self.handle_start_payment(token=token, chat_id=chat_id)):
                return UpdateResult(UpdateKind.INVOICE_SENT, payment)
            return UpdateResult(UpdateKind.IGNORED, None)

        if successful := message.get("successful_payment"):
            try:
                payment, _ = self.record_successful_payment(successful)
                return UpdateResult(UpdateKind.SUCCESSFUL_PAYMENT, payment)
            except InvalidPaymentUpdate as exc:
                logger.warning("Successful payment rejected: %s", exc)
                bale_payment_failed.send(sender=None, error=exc, update=successful)
                raise

        return UpdateResult(UpdateKind.IGNORED, None)

    def _handle_pre_checkout(self, query: dict[str, Any]) -> UpdateResult:
        query_id = query.get("id", "")
        payment: BalePayment | None = None
        try:
            payment = self.approve_pre_checkout(query)
            bale_pre_checkout.send(sender=BalePayment, payment=payment, query=query)
            self.client.answer_pre_checkout_query(query_id, ok=True)
            return UpdateResult(UpdateKind.PRE_CHECKOUT_APPROVED, payment)
        except (PreCheckoutRejected, InvalidPaymentUpdate) as exc:
            logger.warning("Pre-checkout rejected for %s: %s", payment or "unknown", exc)
            bale_payment_failed.send(sender=payment.__class__ if payment else None, error=exc, update=query)
            self.client.answer_pre_checkout_query(query_id, ok=False, error_message=str(exc))
            return UpdateResult(UpdateKind.PRE_CHECKOUT_REJECTED, payment)


_default_service: BalePayService | None = None


def get_service() -> BalePayService:
    """Process-wide service singleton."""
    global _default_service
    if _default_service is None:
        _default_service = BalePayService()
    return _default_service
