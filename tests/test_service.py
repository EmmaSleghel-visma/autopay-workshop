import io
from datetime import date

from fraud_detection.importer import CsvImporter
from fraud_detection.service import import_transactions
from fraud_detection.storage import TransactionStore

HEADER = "transaction_id,debtor_account,creditor_account,amount,currency,due_date\n"
TODAY = date(2026, 10, 23)


def run(store, text, evaluate):
    return import_transactions(io.StringIO(text), CsvImporter(), store, evaluate, TODAY)


def test_duplicates_are_skipped_and_reported(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    run(store, HEADER + "t1,D1,C1,5.00,NOK,2026-11-30\n", lambda *a: [])

    summary = run(
        store,
        HEADER
        + "t1,D1,C1,5.00,NOK,2026-11-30\n"  # already stored
        + "t2,D1,C1,5.00,NOK,2026-11-30\n"
        + "t2,D1,C1,5.00,NOK,2026-11-30\n",  # repeated within the same file
        lambda *a: [],
    )
    assert summary.imported == 1
    assert summary.duplicates == ["t1", "t2"]
    assert [s.transaction.transaction_id for s in store.all()] == ["t1", "t2"]


def test_flags_are_stored_and_counted(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    summary = run(
        store,
        HEADER + "t1,D1,C1,5.00,NOK,2026-11-30\nt2,D1,C1,99999.00,NOK,2026-11-30\n",
        lambda tx, history, day: ["HIGH_AMOUNT"] if tx.transaction_id == "t2" else [],
    )
    assert (summary.imported, summary.flagged) == (2, 1)
    assert [s.flags for s in store.all()] == [(), ("HIGH_AMOUNT",)]


def test_earlier_rows_in_same_file_are_history(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    seen = []

    def evaluate(tx, history, day):
        seen.append((tx.transaction_id, history.debtor_known("D1"), history.has_paid("D1", "C1")))
        assert day == TODAY
        return []

    run(store, HEADER + "t1,D1,C1,5.00,NOK,2026-11-30\nt2,D1,C2,5.00,NOK,2026-11-30\n", evaluate)
    assert seen == [("t1", False, False), ("t2", True, True)]


def test_parse_errors_are_reported(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    summary = run(store, HEADER + "t1,D1,C1,abc,NOK,2026-11-30\n", lambda *a: [])
    assert summary.imported == 0
    assert [e.line for e in summary.errors] == [2]


def test_non_utf8_file_is_rejected_without_crash(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    raw = (HEADER + "t1,Bjørn,C1,5.00,NOK,2026-11-30\n").encode("cp1252")
    source = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    summary = import_transactions(source, CsvImporter(), store, lambda *a: [], TODAY)
    assert summary.imported == 0
    assert "not UTF-8" in summary.errors[0].message
    assert store.all() == []


def test_import_is_all_or_nothing_when_evaluation_fails(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")

    def evaluate(tx, history, day):
        if tx.transaction_id == "t2":
            raise RuntimeError("boom")
        return []

    try:
        run(store, HEADER + "t1,D1,C1,5.00,NOK,2026-11-30\nt2,D1,C1,5.00,NOK,2026-11-30\n", evaluate)
    except RuntimeError:
        pass
    assert store.all() == []  # t1 rolled back with the failed batch


def test_created_date_near_year_9999_does_not_crash_the_import(tmp_path):
    from fraud_detection import rules
    store = TransactionStore(tmp_path / "fraud.db")
    csv_text = (
        "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date\n"
        "t1,D1,C1,5.00,NOK,2026-11-30,9999-10-01\n"
    )
    summary = run(store, csv_text, rules.evaluate)
    assert summary.imported == 1
    assert store.all()[0].flags == ("PAST_DUE_DATE",)  # due 2026 is before created 9999
