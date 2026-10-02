from enum import Enum

__all__ = ["UpdateKind"]


class UpdateKind(str, Enum):
    PRE_CHECKOUT_APPROVED = "pre_checkout_approved"
    PRE_CHECKOUT_REJECTED = "pre_checkout_rejected"
    SUCCESSFUL_PAYMENT = "successful_payment"
    INVOICE_SENT = "invoice_sent"
    IGNORED = "ignored"
