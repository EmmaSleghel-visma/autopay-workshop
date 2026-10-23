from datetime import date
from decimal import Decimal

from fraud_detection.models import Transaction
from fraud_detection.storage import TransactionStore


def tx(tid, debtor="D1", creditor="C1", amount="100.00"):
    return Transaction(tid, debtor, creditor, Decimal(amount), "NOK", date(2026, 11, 30))


def test_transactions_survive_reopen(tmp_path):
    db = tmp_path / "fraud.db"
    store = TransactionStore(db)
    store.add(tx("t1", amount="10000.01"), date(2026, 10, 23), ["HIGH_AMOUNT"])
    store.close()

    reopened = TransactionStore(db)
    [stored] = reopened.all()
    assert stored.transaction == tx("t1", amount="10000.01")
    assert stored.import_date == date(2026, 10, 23)
    assert stored.flags == ("HIGH_AMOUNT",)


def test_history_queries(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    assert not store.debtor_known("D1")
    store.add(tx("t1", "D1", "C1"), date(2026, 10, 23), [])
    assert store.debtor_known("D1")
    assert store.has_paid("D1", "C1")
    assert not store.has_paid("D1", "C2")
    assert not store.has_paid("D2", "C1")
    assert store.exists("t1")
    assert not store.exists("t2")
