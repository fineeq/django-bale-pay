import time
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from django_bale_payments.client import BaleClient
from django_bale_payments.exceptions import BaleAPIError, InvalidPaymentUpdate
from django_bale_payments.services import BalePayService, UpdateKind


class Command(BaseCommand):
    help = "Run a local development long-polling worker to receive payments without tunnels or public IP."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--timeout",
            type=int,
            default=20,
            help="Long-polling timeout in seconds (default: 20).",
        )
        parser.add_argument(
            "--keep-webhook",
            action="store_true",
            help="Do not automatically delete active webhook on startup (getUpdates may fail if webhook is active).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        client = BaleClient()
        timeout = options["timeout"]

        self.stdout.write(self.style.MIGRATE_HEADING("=== Bale Payments Development Polling Worker ==="))
        self.stdout.write("Use this during local development behind NAT/CGNAT without tunnels.")

        if not options.get("keep_webhook"):
            try:
                info = client.get_webhook_info()
                if info.get("url"):
                    self.stdout.write(
                        self.style.WARNING(
                            f"Active webhook detected ({info['url']}). "
                            "Clearing webhook because Bale cannot poll while a webhook is active..."
                        )
                    )
                    client.delete_webhook()
                    self.stdout.write(self.style.SUCCESS("Webhook cleared successfully."))
            except BaleAPIError as exc:
                self.stdout.write(self.style.WARNING(f"Could not verify webhook status: {exc}"))

        self.stdout.write(self.style.SUCCESS("Listening for Bale updates... (Press Ctrl+C to stop)\n"))

        service = BalePayService(client=client)
        offset: int | None = None
        try:
            while True:
                try:
                    updates = client.get_updates(
                        offset=offset,
                        timeout=timeout,
                        allowed_updates=["message", "pre_checkout_query"],
                    )
                except BaleAPIError as exc:
                    self.stdout.write(self.style.WARNING(f"[{timezone.now():%H:%M:%S}] Polling error: {exc}. Retrying in 3s..."))
                    time.sleep(3)
                    continue

                for update in updates:
                    offset = update["update_id"] + 1
                    timestamp = f"[{timezone.now():%H:%M:%S}]"

                    try:
                        result = service.process_update(update)
                    except InvalidPaymentUpdate as exc:
                        self.stdout.write(self.style.ERROR(f"{timestamp} Rejected update: {exc}"))
                        continue

                    payment = result.payment

                    if result.kind == UpdateKind.PRE_CHECKOUT_APPROVED:
                        self.stdout.write(
                            self.style.SUCCESS(f"{timestamp} [PRE-CHECKOUT APPROVED] Ref: {payment.reference}")
                        )
                    elif result.kind == UpdateKind.SUCCESSFUL_PAYMENT:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"{timestamp} [PAYMENT SUCCESSFUL] Ref: {payment.reference} | "
                                f"Total: {payment.amount} {payment.currency}"
                            )
                        )
                    elif result.kind == UpdateKind.INVOICE_SENT:
                        msg_id = payment.metadata.get("bale_message", {}).get("message_id", "-")
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"{timestamp} [INVOICE SENT] Ref: {payment.reference} | "
                                f"Amount: {payment.amount} {payment.currency} | "
                                f"Chat ID: {payment.chat_id} | Bale Message ID: {msg_id}"
                            )
                        )
                    elif result.kind == UpdateKind.PRE_CHECKOUT_REJECTED:
                        self.stdout.write(self.style.WARNING(f"{timestamp} [PRE-CHECKOUT REJECTED]"))

        except KeyboardInterrupt:
            self.stdout.write("\n" + self.style.NOTICE("Polling worker stopped."))
