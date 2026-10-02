import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class Currency(models.TextChoices):
    IRR = "IRR", _("Iranian Rial")
    IRT = "IRT", _("Iranian Toman")


class BalePayment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PAID = "paid", _("Paid")
        REJECTED = "rejected", _("Rejected")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name=_("ID"))
    reference = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_("Reference"),
        help_text=_("Application order or invoice reference."),
    )
    title = models.CharField(
        max_length=255,
        verbose_name=_("Title"),
        help_text=_("Product or service title displayed on the Bale invoice."),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Detailed description displayed on the Bale invoice."),
    )
    amount = models.PositiveBigIntegerField(
        verbose_name=_("Amount"),
        help_text=_("Amount in Iranian Rials (IRR) processed by Bale."),
    )
    currency = models.CharField(
        max_length=4,
        choices=Currency.choices,
        default=Currency.IRR,
        verbose_name=_("Currency"),
        help_text=_("Currency specified when initializing the payment (IRR or IRT)."),
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name=_("Status"),
    )

    # ==============================================================================
    # These fields are populated after the payment is completed and verified by Bale.
    # ==============================================================================
    chat_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Chat ID"),
        help_text=_("Bale chat ID where the invoice was sent."),
    )
    bale_charge_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        verbose_name=_("Bale Charge ID"),
        help_text=_("Unique payment identifier returned by Bale upon successful payment."),
    )
    # ==============================================================================

    metadata = models.JSONField(
            default=dict,
            blank=True,
            verbose_name=_("Metadata"),
            help_text=_("Arbitrary custom key-value metadata stored by the application developer."),
    ) # Json field to store custom metadata related to the payment.

    
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated at"))
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Paid at"))

    class Meta:
        verbose_name = _("Bale Payment")
        verbose_name_plural = _("Bale Payments")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Bale payment {self.reference} ({self.status})"

    @property
    def is_paid(self) -> bool:
        return self.status == self.Status.PAID

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def amount_in_toman(self) -> int:
        """Return the payment amount in Tomans (IRR // 10)."""
        return self.amount // 10


# Backwards compatibility alias
Payment = BalePayment
