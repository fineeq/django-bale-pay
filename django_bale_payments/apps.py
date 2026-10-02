from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DjangoBalePaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_bale_payments"
    verbose_name = _("Bale Payments")

    def ready(self) -> None:
        from . import checks  # noqa: F401
