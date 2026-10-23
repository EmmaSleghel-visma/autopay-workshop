"""Layer 5: import time, tracemalloc peak and store.all() time on generated 10k / 100k / 1M-row files; ceilings are 5-25x the measured values in qa/QUALITY_REPORT.md."""

import os
import random
import time
import tracemalloc
from datetime import timedelta

import pytest

from fraud_detection import rules
from fraud_detection.importer import CsvImporter
from fraud_detection.service import import_transactions
from fraud_detection.storage import TransactionStore
from qa_support import IMPORT_DATE

DEBTORS = 500
CREDITORS = 2000
HEADER = "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date\n"


def account(prefix, n):
    digits = f"{prefix}{n:07d}"
    return f"{digits[:4]}.{digits[4:6]}.{digits[6:]}"


def write_file(path, rows, seed=20261023):
    rnd = random.Random(seed)
    debtors = [account(6000, i) for i in range(DEBTORS)]
    creditors = [account(7000, i) for i in range(CREDITORS)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(HEADER)
        for i in range(rows):
            created = IMPORT_DATE - timedelta(days=rnd.randint(0, 30))
            due = created + timedelta(days=rnd.randint(0, 80))
            amount = f"{rnd.randint(100, 1_200_000) / 100:.2f}"
            f.write(f"T-PERF-{i:07d},{rnd.choice(debtors)},{rnd.choice(creditors)},{amount},NOK,"
                    f"{due.isoformat()},{created.isoformat()}\n")


def run_import(csv_path, db_path, trace_memory):
    store = TransactionStore(db_path)
    try:
        if trace_memory:
            tracemalloc.start()
        start = time.perf_counter()
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            summary = import_transactions(f, CsvImporter(), store, rules.evaluate, IMPORT_DATE)
        elapsed = time.perf_counter() - start
        peak = tracemalloc.get_traced_memory()[1] if trace_memory else 0
        start = time.perf_counter()
        stored = store.all()
        list_s = time.perf_counter() - start
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        store.close()
    return summary, elapsed, peak, list_s, len(stored)


def measure(tmp_path, rows):
    csv_path = tmp_path / f"perf_{rows}.csv"
    write_file(csv_path, rows)
    summary, import_s, _, list_s, stored = run_import(csv_path, tmp_path / "timed.db", trace_memory=False)
    _, _, peak, _, _ = run_import(csv_path, tmp_path / "traced.db", trace_memory=True)
    result = {"rows": rows, "import_s": import_s, "peak_mb": peak / 2**20, "list_s": list_s,
              "rows_per_s": rows / import_s, "imported": summary.imported,
              "errors": len(summary.errors), "stored": stored}
    print(f"\n{'rows':>9} | {'import s':>9} | {'rows/s':>7} | {'peak MB':>8} | {'all() s':>7}\n"
          f"{rows:>9,} | {import_s:>9.2f} | {result['rows_per_s']:>7.0f} | "
          f"{result['peak_mb']:>8.1f} | {list_s:>7.2f}")
    return result


def check(result, rows, max_import_s, max_peak_mb, max_list_s):
    assert (result["imported"], result["errors"], result["stored"]) == (rows, 0, rows)
    assert result["import_s"] < max_import_s, f"{rows:,} rows imported in {result['import_s']:.1f} s"
    assert result["peak_mb"] < max_peak_mb, f"{rows:,} rows peaked at {result['peak_mb']:.1f} MB"
    assert result["list_s"] < max_list_s, f"store.all() on {rows:,} rows took {result['list_s']:.2f} s"


@pytest.mark.slow
def test_import_10k_generated_rows(tmp_path):
    check(measure(tmp_path, 10_000), 10_000, max_import_s=5, max_peak_mb=25, max_list_s=1)


@pytest.mark.slow
def test_import_100k_generated_rows(tmp_path):
    check(measure(tmp_path, 100_000), 100_000, max_import_s=30, max_peak_mb=250, max_list_s=8)


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("QA_HUGE") != "1", reason="1M rows: minutes and ~1 GB RAM; set QA_HUGE=1")
def test_import_1m_generated_rows(tmp_path):
    check(measure(tmp_path, 1_000_000), 1_000_000, max_import_s=300, max_peak_mb=2500, max_list_s=80)
