"""Utility helpers."""


def format_currency(amount):
    """Format a number as Nigerian Naira currency string."""
    if amount is None:
        return "₦0.00"
    return f"₦{float(amount):,.2f}"
