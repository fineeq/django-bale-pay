class BaleAPIError(Exception):
    """The Bale Bot API rejected a request or returned an invalid response."""


class InvalidPaymentUpdate(Exception):
    """A webhook update cannot safely be associated with a payment."""


class PreCheckoutRejected(InvalidPaymentUpdate):
    """Raised in bale_pre_checkout signal handlers to reject an order before charging.

    The exception message will be displayed directly to the customer in the Bale app.
    """

    def __init__(self, message: str = "Payment verification failed") -> None:
        self.message = message
        super().__init__(message)
