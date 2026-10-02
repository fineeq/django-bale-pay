from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True)
class BaleSettings:
    """A simple dataclass for better settings accessibility."""
    bot_token: str
    provider_token: str
    webhook_secret: str | None = None
    bot_username: str | None = None
    webhook_base_url: str | None = None


def get_settings() -> BaleSettings:
    """Return the BaleSettings instance from Django settings."""
    config = getattr(settings, "BALE_PAYMENTS", {})
    bot_token = config.get("BOT_TOKEN")
    provider_token = config.get("PROVIDER_TOKEN")
    webhook_secret = config.get("WEBHOOK_SECRET")
    if not bot_token or not provider_token or not webhook_secret:
        raise ImproperlyConfigured(
            "BALE_PAYMENTS must define BOT_TOKEN, PROVIDER_TOKEN, and WEBHOOK_SECRET."
        )
    return BaleSettings(
        bot_token=bot_token,
        provider_token=provider_token,
        webhook_secret=webhook_secret,
        bot_username=config.get("BOT_USERNAME"),
        webhook_base_url=config.get("WEBHOOK_BASE_URL"),
    )
