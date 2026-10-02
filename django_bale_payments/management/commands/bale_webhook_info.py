from typing import Any

from django.core.management.base import BaseCommand, CommandError

from django_bale_payments.client import BaleClient
from django_bale_payments.exceptions import BaleAPIError


class Command(BaseCommand):
    help = "Inspect or delete the current webhook status on Bale."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete the active webhook on Bale instead of inspecting.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        client = BaleClient()

        if options.get("delete"):
            self.stdout.write("Deleting webhook from Bale...")
            try:
                client.delete_webhook()
                self.stdout.write(self.style.SUCCESS("Successfully deleted webhook from Bale."))
            except BaleAPIError as exc:
                raise CommandError(f"Failed to delete webhook: {exc}") from exc
            return

        self.stdout.write("Fetching webhook info from Bale...")
        try:
            info = client.get_webhook_info()
        except BaleAPIError as exc:
            raise CommandError(f"Failed to fetch webhook info: {exc}") from exc

        url = info.get("url", "")
        if url:
            self.stdout.write(self.style.SUCCESS(f"Active Webhook URL: {url}"))
        else:
            self.stdout.write(self.style.WARNING("No active webhook registered on Bale."))

        pending_count = info.get("pending_update_count", 0)
        self.stdout.write(f"Pending updates count: {pending_count}")

        if last_error_msg := info.get("last_error_message"):
            last_error_date = info.get("last_error_date", "Unknown date")
            self.stdout.write(
                self.style.ERROR(f"Last error: {last_error_msg} (at timestamp {last_error_date})")
            )
        else:
            self.stdout.write("Last error: None (healthy)")

