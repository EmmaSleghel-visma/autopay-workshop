"""Plain-language explanations of the rule codes, for the transactions page."""

from decimal import Decimal

from .. import rules
from ..models import StoredTransaction


def reason(code: str, stored: StoredTransaction) -> str:
    tx = stored.transaction
    start = "the created date" if tx.created_date is not None else "the import date"
    supported = list(rules.HIGH_AMOUNT_LIMITS)
    texts = {
        rules.HIGH_AMOUNT: f"Amount above {tx.currency} {_amount(rules.HIGH_AMOUNT_LIMITS.get(tx.currency))}",
        rules.NEW_CREDITOR: "First payment from this debtor to this creditor",
        rules.FAR_FUTURE_DUE: f"Due date more than {rules.FAR_FUTURE_MONTHS} months after {start}",
        rules.PAST_DUE_DATE: f"Due date before {start}",
        rules.UNSUPPORTED_CURRENCY: (
            f"Currency {tx.currency} is not supported (only {', '.join(supported[:-1])} and {supported[-1]})"
        ),
    }
    return texts.get(code, code)


def _amount(limit: Decimal | None) -> str:
    """10000.00 -> '10 000' (space as thousands separator, as in Norway and Sweden)."""
    return f"{limit:,.0f}".replace(",", " ") if limit is not None else ""
