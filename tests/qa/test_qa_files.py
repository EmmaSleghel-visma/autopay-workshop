"""Layer 3: whole-file cases (header-only, bad header, delimiter, BOM, line endings, ...), each in a fresh store."""

import time

import pytest

from fraud_detection import rules
from fraud_detection.importer import CsvImporter
from fraud_detection.service import import_transactions
from fraud_detection.storage import TransactionStore
from qa_support import IMPORT_DATE, import_file


def file_mismatches(expected, category, tmp_path):
    failures = []
    for f in expected["files"]:
        if f["category"] != category or f["case"] == "FILE-12":
            continue
        store = TransactionStore(tmp_path / f"{f['case']}.db")
        try:
            s = import_file(store, f["file"])
            got = (s.imported, len(s.errors))
            if got != (f["imported"], f["errors"]):
                failures.append(f"{f['case']} {f['file']}: expected imported/errors {(f['imported'], f['errors'])}, got {got} ({f['expect']})")
        except Exception as exc:
            failures.append(f"{f['case']} {f['file']}: crashed with {type(exc).__name__}: {exc} ({f['expect']})")
        finally:
            store.close()
    return failures


def test_negative_files_are_rejected_cleanly(expected, tmp_path):
    failures = file_mismatches(expected, "NEG", tmp_path)
    assert not failures, "\n".join(failures)


def test_corner_files_are_imported(expected, tmp_path):
    failures = file_mismatches(expected, "CORNER", tmp_path)
    assert not failures, "\n".join(failures)


def test_rejected_file_reports_why(store):
    s = import_file(store, "file_bad_header.csv")
    assert [e.line for e in s.errors] == [1]
    assert "missing column" in s.errors[0].message


def test_error_line_numbers_count_blank_lines(tmp_path):
    path = tmp_path / "blank_line.csv"
    path.write_text("transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date\n"
                    "B1,1,2,10.00,NOK,2026-11-01,2026-10-01\n\nB2,1,2,abc,NOK,2026-11-01,2026-10-01\n", encoding="utf-8")
    store = TransactionStore(tmp_path / "blank.db")
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            s = import_transactions(f, CsvImporter(), store, rules.evaluate, IMPORT_DATE)
    finally:
        store.close()
    assert [e.line for e in s.errors] == [4], "the bad row is on physical line 4 of the file"


@pytest.mark.slow
def test_large_file_imports_within_30_seconds(store):
    start = time.perf_counter()
    s = import_file(store, "file_large_10k.csv")
    elapsed = time.perf_counter() - start
    assert (s.imported, len(s.errors)) == (10000, 0)
    assert elapsed < 30, f"10,000 rows took {elapsed:.1f} s"
