"""Fraud rules engine. Owned by Iulia; this file only fixes the contract.

evaluate() is called once per new (non-duplicate) transaction, before it is stored,
and returns the codes of every rule that triggered (empty list = not flagged).

- HIGH_AMOUNT: amount > 10 000.00 NOK (exactly 10 000.00 is not flagged).
- NEW_CREDITOR: history.debtor_known(debtor) and not history.has_paid(debtor, creditor).
  A debtor's first transaction is not flagged. Accounts are already normalized.
- FAR_FUTURE_DUE: due_date more than 3 calendar months after tx.created_date,
  or after import_date when created_date is None (15 Jan -> 15 Apr is the limit).
- UNSUPPORTED_CURRENCY: currency is not "NOK".
"""

from datetime import date

from .models import History, Transaction

HIGH_AMOUNT = "HIGH_AMOUNT"
NEW_CREDITOR = "NEW_CREDITOR"
FAR_FUTURE_DUE = "FAR_FUTURE_DUE"
UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"


def evaluate(tx: Transaction, history: History, import_date: date) -> list[str]:
    raise NotImplementedError("rules engine not implemented yet")
