"""Decision table: every combination of the five rule conditions checked against rules.evaluate."""

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


def build_case(high, new_creditor, due_state, foreign, created):
    tx = Transaction(
        transaction_id="DT",
        debtor_account=DEBTOR,
        creditor_account=NEW_CREDITOR if new_creditor else KNOWN_CREDITOR,
        amount=Decimal("10000.01") if high else Decimal("10000.00"),
        currency="EUR" if foreign else "NOK",
        due_date=DUE_BY_STATE[due_state],
        created_date=created,
    )
    expected = set()
    if high:
        expected.add(rules.HIGH_AMOUNT)
    if new_creditor:
        expected.add(rules.NEW_CREDITOR)
    if due_state != "neither":
        expected.add(due_state)
    if foreign:
        expected.add(rules.UNSUPPORTED_CURRENCY)
    return tx, expected


def check_table(created, import_date):
    history = TableHistory({(DEBTOR, KNOWN_CREDITOR)})
    failures = []
    combos = list(itertools.product([False, True], [False, True], list(DUE_BY_STATE), [False, True]))
    for high, new_creditor, due_state, foreign in combos:
        tx, expected = build_case(high, new_creditor, due_state, foreign, created)
        got = rules.evaluate(tx, history, import_date)
        missing = sorted(expected - set(got))
        extra = sorted(set(got) - expected)
        duplicated = len(got) != len(set(got))
        if missing or extra or duplicated:
            label = (f"high={high} new_creditor={new_creditor} due={due_state} "
                     f"currency={tx.currency} created={created}")
            failures.append(f"{label}: missing {missing}, extra {extra}, got {got}")
    return combos, failures


def test_every_combination_with_created_date():
    combos, failures = check_table(CREATED, IMPORT_DATE)
    assert len(combos) == 24
    assert not failures, "\n".join(failures)


def test_every_combination_falls_back_to_import_date():
    combos, failures = check_table(None, CREATED)
    assert len(combos) == 24
    assert not failures, "\n".join(failures)


def test_first_transaction_of_debtor_never_new_creditor_in_any_combination():
    failures = []
    for high, due_state, foreign in itertools.product([False, True], list(DUE_BY_STATE), [False, True]):
        tx, expected = build_case(high, True, due_state, foreign, CREATED)
        expected.discard(rules.NEW_CREDITOR)
        got = rules.evaluate(tx, TableHistory(set()), IMPORT_DATE)
        if set(got) != expected:
            failures.append(f"high={high} due={due_state} currency={tx.currency}: "
                            f"expected {sorted(expected)}, got {got}")
    assert not failures, "\n".join(failures)
