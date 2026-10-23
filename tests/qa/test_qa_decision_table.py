"""Decision table: currency x amount at/over its limit x creditor x due state, checked against rules.evaluate."""

import itertools
from datetime import date
from decimal import Decimal

from fraud_detection import rules
from fraud_detection.models import Transaction
from qa_support import IMPORT_DATE

DEBTOR = "12345678903"
KNOWN_CREDITOR = "98765432109"
NEW_CREDITOR = "11112222333"
CREATED = date(2026, 1, 31)
DUE_BY_STATE = {
    "FAR_FUTURE_DUE": date(2026, 5, 1),
    "PAST_DUE_DATE": date(2026, 1, 30),
    "neither": date(2026, 4, 30),
}


class TableHistory:
    def __init__(self, pairs):
        self.pairs = frozenset(pairs)

    def debtor_known(self, debtor_account):
        return any(d == debtor_account for d, _ in self.pairs)

    def has_paid(self, debtor_account, creditor_account):
        return (debtor_account, creditor_account) in self.pairs


AT_LIMIT = {"NOK": Decimal("10000.00"), "SEK": Decimal("10000.00"), "EUR": Decimal("1000.00"), "USD": Decimal("10000.00")}
CURRENCIES = list(AT_LIMIT)
OVER = Decimal("0.01")


def build_case(over_limit, new_creditor, due_state, currency, created):
    tx = Transaction(
        transaction_id="DT",
        debtor_account=DEBTOR,
        creditor_account=NEW_CREDITOR if new_creditor else KNOWN_CREDITOR,
        amount=AT_LIMIT[currency] + OVER if over_limit else AT_LIMIT[currency],
        currency=currency,
        due_date=DUE_BY_STATE[due_state],
        created_date=created,
    )
    expected = set()
    if over_limit and currency != "USD":
        expected.add(rules.HIGH_AMOUNT)
    if new_creditor:
        expected.add(rules.NEW_CREDITOR)
    if due_state != "neither":
        expected.add(due_state)
    if currency == "USD":
        expected.add(rules.UNSUPPORTED_CURRENCY)
    return tx, expected


def check_table(created, import_date):
    history = TableHistory({(DEBTOR, KNOWN_CREDITOR)})
    failures = []
    combos = list(itertools.product([False, True], [False, True], list(DUE_BY_STATE), CURRENCIES))
    for over_limit, new_creditor, due_state, currency in combos:
        tx, expected = build_case(over_limit, new_creditor, due_state, currency, created)
        got = rules.evaluate(tx, history, import_date)
        missing = sorted(expected - set(got))
        extra = sorted(set(got) - expected)
        duplicated = len(got) != len(set(got))
        if missing or extra or duplicated:
            label = (f"amount={tx.amount} new_creditor={new_creditor} due={due_state} "
                     f"currency={currency} created={created}")
            failures.append(f"{label}: missing {missing}, extra {extra}, got {got}")
    return combos, failures


def test_every_combination_with_created_date():
    combos, failures = check_table(CREATED, IMPORT_DATE)
    assert len(combos) == 48
    assert not failures, "\n".join(failures)


def test_every_combination_falls_back_to_import_date():
    combos, failures = check_table(None, CREATED)
    assert len(combos) == 48
    assert not failures, "\n".join(failures)


def test_first_transaction_of_debtor_never_new_creditor_in_any_combination():
    failures = []
    for over_limit, due_state, currency in itertools.product([False, True], list(DUE_BY_STATE), CURRENCIES):
        tx, expected = build_case(over_limit, True, due_state, currency, CREATED)
        expected.discard(rules.NEW_CREDITOR)
        got = rules.evaluate(tx, TableHistory(set()), IMPORT_DATE)
        if set(got) != expected:
            failures.append(f"amount={tx.amount} due={due_state} currency={currency}: "
                            f"expected {sorted(expected)}, got {got}")
    assert not failures, "\n".join(failures)
