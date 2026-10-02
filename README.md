<p align="center">
  <img src="https://raw.githubusercontent.com/fineeq/django-bale-pay/main/assets/banner.webp" alt="django-bale-payments banner" width="600" />
</p>

# django-bale-payments

Native **Bale Wallet** payments for Django.

> Status: early development. Test with a Bale test provider token before accepting real
> payments.

## What it provides

- Creates Bale invoices with a signed, order-bound payload.
- Handles `pre_checkout_query` updates and replies to Bale immediately.
- Records `successful_payment` updates idempotently.
- Exposes a small webhook view, a transaction model, and Django signals.

## Installation

```bash
pip install django-bale-payments
```

```python
# settings.py
INSTALLED_APPS = [
  # ......  
  "django_bale_payments"
  # ......  
]

BALE_PAYMENTS = {
    # Required: API authentication token obtained from BotFather
    "BOT_TOKEN": "your-bale-bot-token-here",

    # Required: Payment provider token. Use 'WALLET-TEST-1111111111111111' for sandbox testing
    "PROVIDER_TOKEN": "WALLET-TEST-1111111111111111",

    # Required: Secret token to sign invoice payloads and verify webhook authenticity.
    # Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    "WEBHOOK_SECRET": "your-generated-random-secret",

    # Optional. If omitted, resolved dynamically via Bale getMe API.
    "BOT_USERNAME": "MyBot",

    # Optional. Lets `bale_set_webhook` run with no argument.
    "WEBHOOK_BASE_URL": "https://mystore.ir",
}
```

> **Testing / Sandbox Mode:**
> To test payments without real bank cards or needing an active PSP merchant contract, set `"PROVIDER_TOKEN": "WALLET-TEST-1111111111111111"`. Bale will simulate the payment flow using a test wallet.
>
> 💡 **Need a real Bale Wallet Provider Token?** Follow the step-by-step [Wallet Provider Guide](docs/wallet_provider_guide.md) ([🇮🇷 راهنمای فارسی](docs/wallet_provider_guide_fa.md)) with screenshots explaining how to register your bot with `@BotFather` and obtain your live token.

Run migrations and add the webhook URL:

```bash
python manage.py migrate
```

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    path("payments/bale/", include("django_bale_payments.urls")),
]
```

### Register the Webhook with Bale

Register your deployment's URL with Bale so it sends incoming payment updates to your app:

```bash
# 🚀 1. Pass your base URL (webhook path is appended automatically):
python manage.py bale_set_webhook https://mystore.ir

# 🔗 2. Or pass the full webhook URL directly (auto-detected):
python manage.py bale_set_webhook https://mystore.ir/payments/bale/webhook/

# ⚙️ 3. Or omit the argument if WEBHOOK_BASE_URL is configured in settings:
python manage.py bale_set_webhook
```

> [!TIP]
> 🎯 **Smart URL Handling:**
> `bale_set_webhook` is flexible and forgiving:
> - If you provide a **base URL** (e.g. `https://mystore.ir`), the webhook route (`/payments/bale/webhook/`) is dynamically resolved from your Django URLconf and appended automatically.
> - If you provide the **full webhook URL** (e.g. `https://mystore.ir/payments/bale/webhook/`), it detects that the webhook path is already included and uses it directly without duplicate slashes or errors.
> - If you omit the URL, it automatically falls back to `WEBHOOK_BASE_URL` in your `BALE_PAYMENTS` settings.

Check status or delete anytime:
```bash
python manage.py bale_webhook_info
```


## Usage

All payment operations live on `BalePayService`. Grab the process-wide instance with
`get_service()` (or build your own with a custom `BaleClient`):

`django-bale-payments` supports both **Websites (e-commerce/SaaS)** and **In-Messenger Bots**:

### Flow 1: Web Checkout (No `chat_id` required)
Recommended for websites. When a user clicks "Pay with Bale" on your website, initialize the payment and redirect them to the generated deep link.

```python
from django_bale_payments import Currency, get_service

def checkout_view(request):
    payment, pay_url = get_service().initialize_payment(
        reference=f"order:{order.pk}",
        amount=50_000,
        currency="IRT",  # Or Currency.IRT. Auto-converts to 500,000 Rials (* 10) for Bale!
        title="Premium subscription",
        description="30 days of access",
        metadata={"user_id": request.user.id, "cart_id": 42},  # Arbitrary custom dev data
    )
    # Redirect customer to Bale (e.g. https://ble.ir/MyBot?start=pay_...)
    return redirect(pay_url)
```

**How it works automatically:**
1. Customer is redirected to Bale and taps **Start**.
2. The built-in webhook/polling worker automatically receives the start message, finds the pending order, and sends the official invoice to their chat.
3. Customer clicks **Pay** in Bale.
4. Once paid, the `bale_payment_paid` signal is emitted!

---

### Flow 2: In-Messenger Bots (Direct Chat Invoice)
If you already know the user's `chat_id` (e.g. inside an existing bot conversation), send the invoice directly:

```python
from django_bale_payments import get_service

payment, bale_message = get_service().create_invoice(
    chat_id=bale_chat_id,
    reference=f"order:{order.pk}",
    title="Premium subscription",
    description="30 days of access",
    amount=500_000,  # IRR
    metadata={"user_id": 99},
)
```

---

### Handling Completed Payments (Signals)

When a payment succeeds, the `bale_payment_paid` signal is emitted:

```python
from django.dispatch import receiver
from django_bale_payments.signals import bale_payment_paid

@receiver(bale_payment_paid)
def fulfil_order(sender, payment, **kwargs):
    # sender is BalePayment model class
    order_id = payment.reference.removeprefix("order:")
    user_id = payment.metadata.get("user_id")
    # Mark the matching order as paid inside your own transaction.
```

---

### Pre-Checkout Validation (Checking Inventory & Custom Logic)

When an invoice is sent, the message may sit in the customer's chat for minutes or hours before they tap **Pay**. When the customer finally taps "Pay", Bale sends a `pre_checkout_query` with a **strict 10-second timeout** to verify whether the order is still valid before deducting funds from their wallet/card.

You can connect to the `bale_pre_checkout` signal to execute custom validation (e.g. checking live inventory, stock limits, or account status). If validation fails, raise `PreCheckoutRejected(error_message)`. Bale will immediately abort the charge and display your custom `error_message` as a popup alert on the customer's phone:

```python
from django.dispatch import receiver
from django_bale_payments.signals import bale_pre_checkout
from django_bale_payments.exceptions import PreCheckoutRejected

@receiver(bale_pre_checkout)
def validate_order_before_charge(sender, payment, query, **kwargs):
    order_id = payment.reference.removeprefix("order:")
    order = Order.objects.get(id=order_id)

    # Check live inventory or reservation:
    if not order.has_stock():
        # Bale displays this exact message to the customer:
        raise PreCheckoutRejected("متأسفانه موجودی این محصول به اتمام رسید.")
```

> [!NOTE]
> **Keep your signal fast!** Bale will abort the transaction if your server takes longer than 10 seconds to respond.
> **Best practice:** Reserve inventory when calling `initialize_payment` (e.g. with a 15-minute hold), and use `bale_pre_checkout` as the final safety guard to ensure the reservation has not expired.

---

### Accessing the Model

The model is named `BalePayment` (with `Payment` provided as a convenience alias):

```python
from django_bale_payments import BalePayment

# Direct querying with first-class fields:
payment = BalePayment.objects.get(reference="order:123")
print(payment.title, payment.amount, payment.chat_id, payment.status)
```

### Understanding `reference` vs `metadata`

* **`reference`** (Required `str`, indexed): The bridge between Bale and your own database models. Because this package cannot know your app's specific models (like `Order` or `Subscription`), `reference` stores your application-level identifier (e.g. `f"order:{order.id}"`). When the `bale_payment_paid` signal fires, use `payment.reference` to identify what was paid for.
* **`metadata`** (Optional `dict`): Reserved for arbitrary custom key-values you want to attach to the payment (e.g. `{"user_id": request.user.id, "cart_id": 42}`). It is stored as a `JSONField` and returned with the payment in signal handlers.

---

## Important security notes

- Keep bot and provider tokens in environment variables, never in source control.
- The webhook's shared secret is an application-level guard. Confirm Bale's current
  webhook-authentication guidance before relying on it as the only protection.
- A signed invoice payload and database row protect against modified amount/reference
  values. The webhook also validates amount and currency before marking a row paid.
- Treat every webhook as retryable: the built-in handler is idempotent by payment charge ID.

## Local Development (Behind NAT / CGNAT)

When developing on `localhost:8000`, your machine is usually behind NAT/CGNAT, so Bale cannot send HTTP requests to your local IP directly. You have two options:

### Option 1: Long-Polling Worker (Zero Setup, Recommended)

Open a second terminal and run:

```bash
python manage.py bale_poll
```

This command listens to Bale's Bot API using long-polling (`getUpdates`) and immediately routes payments through your Django app. **No public IP, no ports forwarded, and no tunnels required.**

### Option 2: Cloudflare Tunnel or ngrok

If you prefer testing the actual HTTP webhook endpoint:

1. Start your local tunnel:
   ```bash
   # Using Cloudflare Tunnel:
   cloudflared tunnel --url http://127.0.0.1:8000

   # Or using ngrok:
   ngrok http 8000
   ```
2. Register the tunnel URL with Bale:
   ```bash
   python manage.py bale_set_webhook https://<your-tunnel-subdomain>.trycloudflare.com
   ```

## Development & Testing

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## Requirement
 - Python 3.10+
 - Django 4.2 LTS, 5.0, 5.1+

## License

MIT.
