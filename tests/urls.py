from django.urls import include, path

urlpatterns = [
    path("payments/bale/", include("django_bale_payments.urls")),
]
