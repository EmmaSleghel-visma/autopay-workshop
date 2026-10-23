"""Independent, deliberately naive re-implementation of the fraud rules and an in-memory history replayer."""

import calendar
from datetime import date
from decimal import Decimal

ALL_CODES = ("HIGH_AMOUNT", "NEW_CREDITOR", "FAR_FUTURE_DUE", "PAST_DUE_DATE", "UNSUPPORTED_CURRENCY")


def clean_account(raw):
    return "".join(ch for ch in raw if ch not in " .")


def three_months_later(start):
    year = start.year
    month = start.month + 3
    if month > 12:
        month -= 12
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    day = start.day if start.day <= last_day else last_day
    return date(year, month, day)


class OracleHistory:
    def __init__(self):
        self.debtors = set()
        self.pairs = set()

    def debtor_known(self, debtor_account):
        return debtor_account in self.debtors

    def has_paid(self, debtor_account, creditor_account):
        return (debtor_account, creditor_account) in self.pairs

    def remember(self, debtor_account, creditor_account):
        self.debtors.add(debtor_account)
        self.pairs.add((debtor_account, creditor_account))


def expected_flags(debtor, creditor, amount, currency, due_date, created_date, import_date, history):
    debtor = clean_account(debtor)
    creditor = clean_account(creditor)
    flags = set()
    if Decimal(amount) > Decimal("10000.00"):
        flags.add("HIGH_AMOUNT")
    if debtor in history.debtors and (debtor, creditor) not in history.pairs:
        flags.add("NEW_CREDITOR")
    start = import_date if created_date is None else created_date
    if due_date > three_months_later(start):
        flags.add("FAR_FUTURE_DUE")
    if due_date < start:
        flags.add("PAST_DUE_DATE")
    if currency.upper() != "NOK":
        flags.add("UNSUPPORTED_CURRENCY")
    return sorted(flags)


def replay(rows, import_date):
    history = OracleHistory()
    result = {}
    for row in rows:
        if row["transaction_id"] in result:
            continue
        result[row["transaction_id"]] = expected_flags(
            row["debtor_account"],
            row["creditor_account"],
            row["amount"],
            row["currency"],
            row["due_date"],
            row["created_date"],
            import_date,
            history,
        )
        history.remember(clean_account(row["debtor_account"]), clean_account(row["creditor_account"]))
    return result
