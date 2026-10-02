import logging

from django.contrib import admin
from django.utils import timezone

from .models import BalePayment
from .signals import bale_payment_paid

logger = logging.getLogger(__name__)


@admin.register(BalePayment)
class BalePaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "title",
        "amount",
        "currency",
        "status",
        "chat_id",
        "bale_charge_id",
        "created_at",
        "paid_at",
    )
    list_filter = ("status", "currency", "created_at", "paid_at")
    search_fields = ("reference", "title", "chat_id", "bale_charge_id", "id")
    readonly_fields = ("id", "created_at", "updated_at")
    date_hierarchy = "created_at"
    actions = ["mark_as_paid"]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "reference",
                    "title",
                    "description",
                    "amount",
                    "currency",
                    "status",
                )
            },
        ),
        (
            "Bale Transaction Details",
            {
                "fields": (
                    "chat_id",
                    "bale_charge_id",
                    "paid_at",
                    "metadata",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.action(description="Mark selected payments as Paid")
    def mark_as_paid(self, request, queryset):
        count = 0
        now = timezone.now()
        for payment in queryset.exclude(status=BalePayment.Status.PAID):
            payment.status = BalePayment.Status.PAID
            if not payment.paid_at:
                payment.paid_at = now
            payment.save(update_fields=["status", "paid_at", "updated_at"])
            responses = bale_payment_paid.send_robust(sender=BalePayment, payment=payment)
            for receiver, response in responses:
                if isinstance(response, Exception):
                    logger.error(
                        "Error executing signal receiver %s for payment %s: %s",
                        receiver,
                        payment.pk,
                        response,
                        exc_info=response,
                    )
            count += 1
        self.message_user(request, f"{count} payment(s) marked as paid.")

    def save_model(self, request, obj, form, change):
        is_newly_paid = change and "status" in form.changed_data and obj.status == BalePayment.Status.PAID
        if is_newly_paid and not obj.paid_at:
            obj.paid_at = timezone.now()
        super().save_model(request, obj, form, change)
        if is_newly_paid:
            responses = bale_payment_paid.send_robust(sender=BalePayment, payment=obj)
            for receiver, response in responses:
                if isinstance(response, Exception):
                    logger.error(
                        "Error executing signal receiver %s for payment %s: %s",
                        receiver,
                        obj.pk,
                        response,
                        exc_info=response,
                    )


PaymentAdmin = BalePaymentAdmin
