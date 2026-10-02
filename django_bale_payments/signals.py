from django.dispatch import Signal

# Emitted when a payment is successfully completed and verified.
# Sender: BalePayment model class
# Keyword arguments:
#   payment: BalePayment instance
bale_payment_paid = Signal()

# Emitted right before answering a pre-checkout query to Bale.
# Raise PreCheckoutRejected(error_message) in a receiver to cancel the payment
# before the user's card/wallet is charged. The error_message will be shown to the user.
# Sender: BalePayment model class
# Keyword arguments:
#   payment: BalePayment instance
#   query: raw pre_checkout_query dict from Bale
bale_pre_checkout = Signal()

# Emitted when an invoice is sent to a customer's chat.
# Sender: BalePayment model class
# Keyword arguments:
#   payment: BalePayment instance
#   chat_id: int | str
bale_invoice_sent = Signal()

# Emitted when a payment cannot be verified or fails during webhook processing.
# Sender: None or BalePayment
# Keyword arguments:
#   error: Exception or str describing the failure
#   update: raw update payload dict from Bale
bale_payment_failed = Signal()
