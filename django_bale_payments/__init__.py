"""Django integration for Bale Wallet's invoice payment flow."""

__version__ = "0.1.0"

__all__ = [
    "BaleAPIError",
    "BaleClient",
    "BalePayService",
    "BalePayment",
    "Currency",
    "InvalidPaymentUpdate",
    "Payment",
    "PreCheckoutRejected",
    "UpdateKind",
    "UpdateResult",
    "bale_invoice_sent",
    "bale_payment_failed",
    "bale_payment_paid",
    "bale_pre_checkout",
    "get_client",
    "get_service",
]


def __getattr__(name: str):
    """Lazy imports to prevent AppRegistryNotReady errors during Django startup."""
    if name == "UpdateKind":
        from . import enums

        return getattr(enums, name)
    if name in ("BalePayService", "UpdateResult", "get_service"):
        from . import services

        return getattr(services, name)
    if name in ("BalePayment", "Payment", "Currency"):
        from . import models

        return getattr(models, name)
    if name in ("BaleClient", "get_client"):
        from . import client

        return getattr(client, name)
    if name in ("bale_payment_paid", "bale_payment_failed", "bale_invoice_sent", "bale_pre_checkout"):
        from . import signals

        return getattr(signals, name)
    if name in ("BaleAPIError", "InvalidPaymentUpdate", "PreCheckoutRejected"):
        from . import exceptions

        return getattr(exceptions, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
