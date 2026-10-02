import json
import logging

from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .conf import get_settings
from .exceptions import BaleAPIError, InvalidPaymentUpdate
from .services import get_service

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def webhook(request: HttpRequest) -> JsonResponse:
    """Handle incoming webhook updates from Bale Bot API."""
    config = get_settings()
    if config.webhook_secret and not constant_time_compare(
        request.headers.get("X-Bale-Webhook-Secret", ""), config.webhook_secret
    ):
        logger.warning("Bale webhook rejected: invalid or missing X-Bale-Webhook-Secret")
        return HttpResponseForbidden("Invalid webhook secret")

    try:
        update = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Bale webhook rejected: invalid JSON payload")
        return HttpResponseBadRequest("Expected a JSON update")

    try:
        result = get_service().process_update(update)
    except InvalidPaymentUpdate as exc:
        logger.warning("Bale webhook failed: %s", exc)
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except BaleAPIError as exc:
        logger.error("Bale API communication error: %s", exc)
        return JsonResponse({"ok": False, "error": "Unable to contact Bale"}, status=502)

    payment = result.payment
    logger.info(
        "Bale webhook handled successfully: kind=%s, payment=%s",
        result.kind.value,
        payment.pk if payment else None,
    )
    return JsonResponse(
        {"ok": True, "kind": result.kind.value, "payment_id": str(payment.pk) if payment else None}
    )
