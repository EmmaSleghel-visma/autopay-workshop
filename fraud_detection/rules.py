"""Fraud rules engine. Owned by Iulia; this file only fixes the contract.

evaluate() is called once per new (non-duplicate) transaction, before it is stored,
and returns the codes of every rule that triggered (empty list = not flagged).

- HIGH_AMOUNT: amount above HIGH_AMOUNT_LIMITS for the transaction's currency
  (NOK 10 000, SEK 10 000, EUR 1 000; exactly the limit is not flagged). No conversion;
  a currency without a limit gets no HIGH_AMOUNT, only UNSUPPORTED_CURRENCY.
- NEW_CREDITOR: history.debtor_known(debtor) and not history.has_paid(debtor, creditor).
  A debtor's first transaction is not flagged. Accounts are already normalized.
- FAR_FUTURE_DUE: due_date more than 3 calendar months after tx.created_date,
  or after import_date when created_date is None (15 Jan -> 15 Apr is the limit).
  When the day does not exist in the target month, use its last day (31 Jan -> 30 Apr).
- PAST_DUE_DATE: due_date before tx.created_date, or before import_date when
  created_date is None. Flagged for manual review, not rejected.
- UNSUPPORTED_CURRENCY: currency is not NOK, SEK or EUR. All other rules still apply.

Amounts are always > 0: the importer rejects zero and negative amounts.
"""

import calendar
from datetime import date
from decimal import Decimal

from .models import History, Transaction

HIGH_AMOUNT = "HIGH_AMOUNT"
NEW_CREDITOR = "NEW_CREDITOR"
FAR_FUTURE_DUE = "FAR_FUTURE_DUE"
PAST_DUE_DATE = "PAST_DUE_DATE"
UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"

# HIGH_AMOUNT thresholds per supported currency, in that currency (no conversion).
# Product Owner decision 2026-10-23. A currency not listed here is UNSUPPORTED_CURRENCY.
HIGH_AMOUNT_LIMITS = {
    "NOK": Decimal("10000.00"),
    "SEK": Decimal("10000.00"),
    "EUR": Decimal("1000.00"),
}
FAR_FUTURE_MONTHS = 3


def evaluate(tx: Transaction, history: History, import_date: date) -> list[str]:
    flags = []
    limit = HIGH_AMOUNT_LIMITS.get(tx.currency)
    if limit is not None and tx.amount > limit:
        flags.append(HIGH_AMOUNT)
    if history.debtor_known(tx.debtor_account) and not history.has_paid(
        tx.debtor_account, tx.creditor_account
    ):
        flags.append(NEW_CREDITOR)
    start = tx.created_date if tx.created_date is not None else import_date
    if tx.due_date > _add_months(start, FAR_FUTURE_MONTHS):
        flags.append(FAR_FUTURE_DUE)
    if tx.due_date < start:
        flags.append(PAST_DUE_DATE)
    if limit is None:
        flags.append(UNSUPPORTED_CURRENCY)
    return flags


def _add_months(day: date, months: int) -> date:
    """Same day of the month, `months` later; clamped to the last day of a shorter month."""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    if year > date.max.year:  # e.g. a 9999-10-01 typo: no due date can be later than this
        return date.max
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
