import json
import logging
import sys
from functools import cached_property
from types import TracebackType
from typing import Any

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

import httpx
from django.core.exceptions import ImproperlyConfigured

from .conf import BaleSettings, get_settings
from .exceptions import BaleAPIError

logger = logging.getLogger(__name__)

BALE_API_BASE_URL = "https://tapi.bale.ai"


class BaleClient:
    """Client for the public Bale Bot API with connection pooling."""

    def __init__(
        self,
        config: BaleSettings | None = None,
        api_base_url: str = BALE_API_BASE_URL,
        timeout: float = 15.0,
        max_connections: int = 20,
        max_keepalive_connections: int = 10,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or get_settings()
        self.api_base_url = api_base_url.rstrip("/")
        self.default_timeout = timeout

        if client is not None:
            self._client = client
        else:
            limits = httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            )
            transport = httpx.HTTPTransport(retries=2)
            self._client = httpx.Client(
                limits=limits,
                transport=transport,
                timeout=httpx.Timeout(timeout, connect=5.0),
            )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def call(self, method: str, payload: dict[str, Any], timeout: float | None = None) -> Any:
        url = f"{self.api_base_url}/bot{self.config.bot_token}/{method}"
        req_timeout = timeout if timeout is not None else self.default_timeout

        logger.debug("Calling Bale API method %s with payload: %s", method, payload)
        try:
            response = self._client.post(url, json=payload, timeout=req_timeout)
            data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Bale API request to %s failed: %s", method, exc)
            raise BaleAPIError(f"Bale API request to {method} failed") from exc

        if not data.get("ok"):
            error_desc = data.get("description", f"Bale API rejected {method}")
            logger.warning("Bale API rejected %s: %s", method, error_desc)
            raise BaleAPIError(error_desc)

        return data.get("result")

    def send_message(self, chat_id: int | str, text: str) -> Any:
        """Send a basic text message to a chat."""
        return self.call("sendMessage", {"chat_id": chat_id, "text": text})

    def send_invoice(
        self,
        chat_id: int | str,
        title: str,
        description: str,
        payload: str,
        prices: list[dict[str, Any]],
        provider_token: str | None = None,
        currency: str = "IRR",
        photo_url: str | None = None,
        **extra: Any,
    ) -> Any:
        """Send an interactive payment invoice card to a chat."""
        token = provider_token or self.config.provider_token
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "title": title,
            "description": description,
            "payload": payload,
            "provider_token": token,
            "currency": currency,
            "prices": prices,
            **extra,
        }
        if photo_url:
            data["photo_url"] = photo_url
        return self.call("sendInvoice", data)


    def answer_pre_checkout_query(self, query_id: str, ok: bool, error_message: str | None = None) -> Any:
        """
        Responds to Bale's 10-second pre-checkout authorization window.
        Bale pauses the checkout flow and queries your server before redirecting
        the customer to the bank. Use this window to verify that items remain in stock
        and order pricing has not changed.
        """
        payload: dict[str, Any] = {"pre_checkout_query_id": query_id, "ok": ok}
        if error_message:
            payload["error_message"] = error_message
        return self.call("answerPreCheckoutQuery", payload)

    def inquire_transaction(self, payment_charge_id: str) -> Any:
        return self.call("inquireTransaction", {"payment_charge_id": payment_charge_id})

    def set_webhook(
        self,
        url: str,
        secret_token: str | None = None,
        allowed_updates: list[str] | None = None,
    ) -> Any:
        """Registers the webhook URL with Bale Bot API."""
        payload: dict[str, Any] = {"url": url}
        secret = secret_token or self.config.webhook_secret
        if secret:
            payload["secret_token"] = secret
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        return self.call("setWebhook", payload)

    def get_webhook_info(self) -> dict[str, Any]:
        """Gets current webhook status from Bale Bot API."""
        return self.call("getWebhookInfo", {})

    def delete_webhook(self) -> Any:
        """Clears the webhook URL from Bale Bot API."""
        return self.call("deleteWebhook", {})

    def get_updates(
        self,
        offset: int | None = None,
        limit: int = 100,
        timeout: int = 20,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch pending updates from Bale via long polling."""
        payload: dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        result = self.call("getUpdates", payload, timeout=timeout + 10)
        return result if isinstance(result, list) else []

    @cached_property
    def me(self) -> dict[str, Any]:
        """Fetch and cache basic bot information from Bale Bot API."""
        return self.call("getMe", {})

    def get_me(self) -> dict[str, Any]:
        """Get basic information about the bot (including username)."""
        return self.me

    @property
    def bot_username(self) -> str:
        """Resolve and return the bot username without a leading '@'.

        Uses settings.BALE_PAYMENTS['BOT_USERNAME'] if defined;
        otherwise dynamically resolves and caches it via getMe.
        """
        if self.config.bot_username:
            return self.config.bot_username.lstrip("@")
        username = self.me.get("username")
        if not username:
            raise ImproperlyConfigured(
                "BALE_PAYMENTS must define 'BOT_USERNAME' or the bot must have a public username on Bale."
            )
        return username.lstrip("@")


_default_client: BaleClient | None = None


def get_client() -> BaleClient:
    """Return a process-local singleton BaleClient with connection pooling.

    Lazily initialized on first use to ensure sockets are never created before
    Gunicorn/uWSGI worker processes fork.
    """
    global _default_client
    if _default_client is None:
        _default_client = BaleClient()
    return _default_client

