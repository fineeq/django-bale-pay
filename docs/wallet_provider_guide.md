# How to Get a Bale Wallet Provider Token

[🇮🇷 راهنمای فارسی (Farsi Guide)](wallet_provider_guide_fa.md)

> [!IMPORTANT]
> ⚠️ 🏦 💳 **Note:** For now, wallet verification and payouts are only available with **Bank Melli Iran (BMI)**.

This guide walks you through obtaining a live **Bale Wallet Provider Token** (`PROVIDER_TOKEN`) from Bale's official `@BotFather`.

---

## Sandbox vs. Live Mode

1. **Sandbox / Testing Mode:**
   If you don't have a Bank Melli account or just want to test your integration locally, you don't need to do any verification. Simply use the static sandbox token directly in your `settings.py`:
   ```python
   "PROVIDER_TOKEN": "WALLET-TEST-1111111111111111"
   ```

2. **Production / Live Mode:**
   Follow the steps below to enable wallet settlements for your bot and get your production token.

---

## Step-by-Step Instructions

*(Buttons to tap at each step are highlighted with red boxes in the screenshots below)*

### 1. Open BotFather
Open [@BotFather](https://ble.ir/BotFather) in Bale and tap **«بازوهای من»** (*My Bots*).

<p align="center">
  <img src="../assets/guide/1_botfather_menu.jpg" alt="Step 1 - BotFather Main Menu" width="400px" />
</p>

---

### 2. Select Your Bot
Select the bot you want to connect to payments from the list.

<p align="center">
  <img src="../assets/guide/2_select_bot.jpg" alt="Step 2 - Select Bot" width="300px" />
</p>

---

### 3. Open Payment Settings
Tap **«پرداخت در بازو»** (*Payments in Bot*).

<p align="center">
  <img src="../assets/guide/3_bot_payments.jpg" alt="Step 3 - Bot Payment Settings" width="350px" />
</p>

---

### 4. Enable Wallet Payments
Tap **«فعال‌سازی پرداخت کیف پولی»** (*Enable Wallet Payments*).  
*(The sandbox test token `WALLET-TEST-1111111111111111` is also displayed in this message if needed).*

<p align="center">
  <img src="../assets/guide/4_enable_wallet.jpg" alt="Step 4 - Enable Wallet Payments" width="450px" />
</p>

---

### 5. Upgrade Wallet to Level 2 (KYC)
For settlement compliance, tap **«ثبت اطلاعات بانکی»** (*Register Bank Details*) to open the verification form.

<p align="center">
  <img src="../assets/guide/5_upgrade_level2.jpg" alt="Step 5 - Upgrade Wallet Prompt" width="450px" />
</p>

---

### 6. Enter Bank Melli Card Details
Enter your Bank Melli debit card or account details and tap **«تایید»** (*Confirm*).

<p align="center">
  <img src="../assets/guide/6_bank_info.jpg" alt="Step 6 - Bank Information Form" width="450px" />
</p>

After submitting:
1. Return to the chat with `@BotFather`.
2. Tap **«کیف‌پولم سطح ۲ شد.»** (*My Wallet is Level 2*).
3. BotFather will issue your official **Production Provider Token**.

---

### 7. Configure in Django

Put your token in your `.env` file:

```bash
# .env
BALE_BOT_TOKEN="123456789:AA..."
BALE_PROVIDER_TOKEN="your-production-provider-token"
```

And add it to your `settings.py`:

```python
import os

BALE_PAYMENTS = {
    "BOT_TOKEN": os.environ["BALE_BOT_TOKEN"],
    "PROVIDER_TOKEN": os.environ["BALE_PROVIDER_TOKEN"],
    "WEBHOOK_SECRET": os.environ.get("BALE_WEBHOOK_SECRET", "strong-random-secret"),
}
```

---

## Security Best Practices

> [!WARNING]
> Keep your tokens secret and never commit them to version control.
> If your token is ever leaked, revoke and regenerate it immediately in `@BotFather` > your bot > **بازیابی توکن** (*Regenerate Token*).
