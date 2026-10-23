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


def _rows(n):
    header = "transaction_id,debtor_account,creditor_account,amount,currency,due_date\n"
    return header + "".join(f"X{i},D{i % 50},C{i % 9},10.00,NOK,2026-11-30\n" for i in range(n))


def _import_in_threads(stores, text):
    import io
    import threading

    from fraud_detection.importer import CsvImporter
    from fraud_detection.service import import_transactions

    results, errors = [], []

    def work(store):
        try:
            results.append(import_transactions(io.StringIO(text), CsvImporter(), store, lambda *a: [], date(2026, 10, 23)))
        except Exception as exc:  # noqa: BLE001 - the test asserts there are none
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(s,)) for s in stores]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results, errors


def test_concurrent_imports_on_separate_connections_do_not_crash(tmp_path):
    db = tmp_path / "fraud.db"
    results, errors = _import_in_threads([TransactionStore(db), TransactionStore(db)], _rows(5000))
    assert errors == []
    assert sorted((r.imported, len(r.duplicates)) for r in results) == [(0, 5000), (5000, 0)]
    assert len(TransactionStore(db).all()) == 5000


def test_concurrent_imports_sharing_one_store_do_not_crash(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    results, errors = _import_in_threads([store, store], _rows(5000))
    assert errors == []
    assert sorted((r.imported, len(r.duplicates)) for r in results) == [(0, 5000), (5000, 0)]
    assert len(store.all()) == 5000


def test_corrupt_database_file_gives_a_clear_error(tmp_path):
    import pytest

    from fraud_detection.storage import StorageError

    db = tmp_path / "fraud.db"
    db.write_bytes(b"this is not a database" * 100)
    with pytest.raises(StorageError, match="not a valid database file.*backup"):
        TransactionStore(db)
