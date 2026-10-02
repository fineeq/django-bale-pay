from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, Warning, register


@register(Tags.compatibility)
def check_bale_settings(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Checks that BALE_PAYMENTS is configured correctly in settings.py."""
    messages: list[CheckMessage] = []
    config = getattr(settings, "BALE_PAYMENTS", None)

    if config is None:
        messages.append(
            Warning(
                "BALE_PAYMENTS setting is missing in settings.",
                hint="Add BALE_PAYMENTS = {'BOT_TOKEN': ..., 'PROVIDER_TOKEN': ...} to your Django settings.",
                id="django_bale_payments.W001",
            )
        )
        return messages

    if not isinstance(config, dict):
        messages.append(
            Error(
                "BALE_PAYMENTS must be a dictionary.",
                id="django_bale_payments.E001",
            )
        )
        return messages

    if not config.get("BOT_TOKEN"):
        messages.append(
            Error(
                "BALE_PAYMENTS is missing 'BOT_TOKEN'.",
                hint="Define 'BOT_TOKEN' in BALE_PAYMENTS.",
                id="django_bale_payments.E002",
            )
        )

    if not config.get("PROVIDER_TOKEN"):
        messages.append(
            Error(
                "BALE_PAYMENTS is missing 'PROVIDER_TOKEN'.",
                hint="Define 'PROVIDER_TOKEN' in BALE_PAYMENTS (for testing, use 'WALLET-TEST-1111111111111111').",
                id="django_bale_payments.E003",
            )
        )

    if not config.get("WEBHOOK_SECRET"):
        messages.append(
            Error(
                "BALE_PAYMENTS is missing 'WEBHOOK_SECRET'.",
                hint="Define 'WEBHOOK_SECRET' in BALE_PAYMENTS.",
                id="django_bale_payments.E004",
            )
        )

    if (
        "BOT_USERNAME" in config
        and config["BOT_USERNAME"] is not None
        and not isinstance(config["BOT_USERNAME"], str)
    ):
        messages.append(
            Error(
                "BALE_PAYMENTS 'BOT_USERNAME' must be a string.",
                id="django_bale_payments.E005",
            )
        )

    return messages

