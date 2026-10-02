from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from django_bale_payments.client import BaleClient
from django_bale_payments.conf import get_settings
from django_bale_payments.exceptions import BaleAPIError


class Command(BaseCommand):
    help = "Register your webhook endpoint with the Bale Bot API."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "url",
            nargs="?",
            type=str,
            help="Public base URL (e.g. https://mystore.ir) or full webhook URL of this deployment. "
            "If only the base URL is provided, the webhook path is appended automatically. "
            "Defaults to WEBHOOK_BASE_URL in BALE_PAYMENTS settings.",
        )
        parser.add_argument(
            "--secret",
            type=str,
            default=None,
            help="Custom webhook secret (defaults to WEBHOOK_SECRET in BALE_PAYMENTS settings).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        config = get_settings()
        raw_url = (options.get("url") or options.get("base_url") or config.webhook_base_url or "").rstrip("/")
        if not raw_url:
            raise CommandError(
                "Provide the deployment's base URL (e.g. https://mystore.ir), the full webhook URL, "
                "or set WEBHOOK_BASE_URL in BALE_PAYMENTS."
            )

        webhook_path = reverse("django_bale_payments:webhook")
        clean_webhook_path = webhook_path.rstrip("/")
        if raw_url.endswith(clean_webhook_path):
            url = raw_url.rstrip("/") + ("/" if webhook_path.endswith("/") else "")
        else:
            url = raw_url + webhook_path
        secret = options.get("secret") or config.webhook_secret

        if not url.startswith("https://"):
            self.stdout.write(
                self.style.WARNING(
                    f"Warning: '{url}' does not start with https://. Bale requires an HTTPS URL."
                )
            )

        self.stdout.write(f"Registering webhook with Bale: {url}...")
        client = BaleClient(config)
        try:
            client.set_webhook(url=url, secret_token=secret)
            self.stdout.write(self.style.SUCCESS(f"Successfully registered webhook: {url}"))
        except BaleAPIError as exc:
            raise CommandError(f"Failed to register webhook with Bale: {exc}") from exc
