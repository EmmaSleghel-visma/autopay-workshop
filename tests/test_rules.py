import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from fraud_detection.importer import CsvImporter
from fraud_detection.models import Transaction
from fraud_detection.rules import (
    FAR_FUTURE_DUE,
    HIGH_AMOUNT,
    NEW_CREDITOR,
    PAST_DUE_DATE,
    UNSUPPORTED_CURRENCY,
    evaluate,
)
from fraud_detection.service import import_transactions
from fraud_detection.storage import TransactionStore

TODAY = date(2026, 10, 23)
HEADER = "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date\n"
SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "transactions.csv"


class FakeHistory:
    def __init__(self, paid=()):
        self._paid = set(paid)

    def debtor_known(self, debtor_account):
        return any(debtor == debtor_account for debtor, _ in self._paid)

    def has_paid(self, debtor_account, creditor_account):
        return (debtor_account, creditor_account) in self._paid


def tx(amount="100.00", currency="NOK", due=date(2026, 11, 1), created=date(2026, 10, 1),
       debtor="D1", creditor="C1"):
    return Transaction("t1", debtor, creditor, Decimal(amount), currency, due, created)


def flags_of(transaction, history=None):
    return evaluate(transaction, history or FakeHistory(), TODAY)


def test_ordinary_transaction_is_not_flagged():
    assert flags_of(tx()) == []


# Rule 1: HIGH_AMOUNT

def test_exactly_10000_is_not_high_amount():
    assert flags_of(tx(amount="10000.00")) == []


def test_10000_01_is_high_amount():
    assert flags_of(tx(amount="10000.01")) == [HIGH_AMOUNT]


# Rule 2: NEW_CREDITOR

def test_first_transaction_of_a_debtor_is_not_new_creditor():
    assert flags_of(tx(), FakeHistory()) == []


def test_known_debtor_paying_known_creditor_is_not_new_creditor():
    assert flags_of(tx(creditor="A"), FakeHistory({("D1", "A")})) == []


def test_known_debtor_paying_new_creditor_is_new_creditor():
    assert flags_of(tx(creditor="B"), FakeHistory({("D1", "A")})) == [NEW_CREDITOR]


def test_a_then_b_flags_only_b(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    import_transactions(
        io.StringIO(HEADER + "a,D1,A,5.00,NOK,2026-11-01,\nb,D1,B,5.00,NOK,2026-11-01,\n"),
        CsvImporter(), store, evaluate, TODAY,
    )
    assert [(s.transaction.transaction_id, s.flags) for s in store.all()] == [
        ("a", ()),
        ("b", (NEW_CREDITOR,)),
    ]


# Rule 3: FAR_FUTURE_DUE

def test_due_exactly_3_months_after_created_date_is_not_flagged():
    assert flags_of(tx(created=date(2026, 1, 15), due=date(2026, 4, 15))) == []


def test_due_3_months_and_1_day_after_created_date_is_far_future():
    assert flags_of(tx(created=date(2026, 1, 15), due=date(2026, 4, 16))) == [FAR_FUTURE_DUE]


def test_3_months_crosses_the_year_end():
    assert flags_of(tx(created=date(2026, 11, 15), due=date(2027, 2, 15))) == []
    assert flags_of(tx(created=date(2026, 11, 15), due=date(2027, 2, 16))) == [FAR_FUTURE_DUE]


def test_without_created_date_counts_from_import_date():
    assert flags_of(tx(created=None, due=date(2027, 1, 23))) == []
    assert flags_of(tx(created=None, due=date(2027, 1, 24))) == [FAR_FUTURE_DUE]


def test_month_end_uses_last_day_of_shorter_month():
    assert flags_of(tx(created=date(2026, 1, 31), due=date(2026, 4, 30))) == []
    assert flags_of(tx(created=date(2026, 1, 31), due=date(2026, 5, 1))) == [FAR_FUTURE_DUE]


def test_month_end_in_a_leap_year():
    assert flags_of(tx(created=date(2027, 11, 30), due=date(2028, 2, 29))) == []
    assert flags_of(tx(created=date(2027, 11, 30), due=date(2028, 3, 1))) == [FAR_FUTURE_DUE]


# PAST_DUE_DATE

def test_due_date_before_created_date_is_past_due():
    assert flags_of(tx(created=date(2026, 10, 1), due=date(2026, 9, 30))) == [PAST_DUE_DATE]


def test_due_date_on_created_date_is_not_past_due():
    assert flags_of(tx(created=date(2026, 10, 1), due=date(2026, 10, 1))) == []


def test_without_created_date_past_due_counts_from_import_date():
    assert flags_of(tx(created=None, due=date(2026, 10, 22))) == [PAST_DUE_DATE]
    assert flags_of(tx(created=None, due=date(2026, 10, 23))) == []


# Rule 4: UNSUPPORTED_CURRENCY

def test_nok_sek_and_eur_are_supported():
    for currency in ("NOK", "SEK", "EUR"):
        assert flags_of(tx(amount="500.00", currency=currency)) == []


def test_high_amount_limit_per_currency_without_conversion():
    for currency, limit in (("NOK", "10000.00"), ("SEK", "10000.00"), ("EUR", "1000.00")):
        assert flags_of(tx(amount=limit, currency=currency)) == []
        above = str(Decimal(limit) + Decimal("0.01"))
        assert flags_of(tx(amount=above, currency=currency)) == [HIGH_AMOUNT]


def test_other_currency_is_unsupported_and_gets_no_high_amount():
    assert flags_of(tx(amount="25000.00", currency="USD")) == [UNSUPPORTED_CURRENCY]


def test_unsupported_currency_still_gets_the_other_rules():
    transaction = tx(amount="25000.00", currency="USD", created=date(2026, 1, 15),
                     due=date(2026, 6, 1), creditor="B")
    assert flags_of(transaction, FakeHistory({("D1", "A")})) == [
        NEW_CREDITOR,
        FAR_FUTURE_DUE,
        UNSUPPORTED_CURRENCY,
    ]


def test_unsupported_currency_past_due_date_gets_both_flags():
    assert flags_of(tx(currency="DKK", created=date(2026, 10, 1), due=date(2026, 9, 1))) == [
        PAST_DUE_DATE,
        UNSUPPORTED_CURRENCY,
    ]


# All rules together

def test_every_triggered_rule_is_returned():
    transaction = tx(amount="25000.00", created=date(2026, 1, 15), due=date(2026, 6, 1),
                     creditor="B")
    assert flags_of(transaction, FakeHistory({("D1", "A")})) == [
        HIGH_AMOUNT,
        NEW_CREDITOR,
        FAR_FUTURE_DUE,
    ]


def test_sample_file_gets_the_documented_flags(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    with SAMPLES.open(newline="") as source:
        import_transactions(source, CsvImporter(), store, evaluate, TODAY)
    assert {s.transaction.transaction_id: s.flags for s in store.all()} == {
        "T001": (),
        "T002": (),
        "T003": (NEW_CREDITOR,),
        "T004": (),
        "T005": (HIGH_AMOUNT,),
        "T006": (),
        "T007": (FAR_FUTURE_DUE,),
        "T008": (),  # no created_date: 2026-12-01 is within 3 months of TODAY
        "T009": (UNSUPPORTED_CURRENCY,),
        "T010": (HIGH_AMOUNT, FAR_FUTURE_DUE),
    }
