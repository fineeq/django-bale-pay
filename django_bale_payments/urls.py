from django.urls import path

from .views import webhook

app_name = "django_bale_payments"

urlpatterns = [path("webhook/", webhook, name="webhook")]
