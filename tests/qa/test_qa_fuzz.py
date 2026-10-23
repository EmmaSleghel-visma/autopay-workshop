"""Robustness: Hypothesis fuzzing of the CSV and pain.001 importers and of the full import pipeline."""

import csv
import io
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from hypothesis import HealthCheck, given, settings, strategies as st

from fraud_detection import rules
from fraud_detection.importer import CsvImporter
from fraud_detection.models import ParseResult, Transaction
from fraud_detection.pain001 import Pain001Importer
from fraud_detection.service import import_transactions
from fraud_detection.storage import TransactionStore

FUZZ = settings(
    derandomize=True,
    deadline=None,
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.large_base_example],
)
IMPORT_DATE = date(2026, 10, 23)
HEADER = "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date"
VALID_CSV = (
    HEADER + "\r\n"
    "T001,1234.56.78903,9876.54.32109,500.00,NOK,2026-11-15,2026-10-20\r\n"
    "T002,1234 56 78903,9876 54 32109,750.00,NOK,2026-11-20,2026-10-21\r\n"
    "T-ÆØÅ-3,1234.56.78903,5555.66.77777,1200.00,eur,2026-11-25,\r\n"
    "\"T,004\",\"2222.33.44444\",9876.54.32109,10000.00,NOK,2026-11-30,2026-10-22\r\n"
)
VALID_PAIN001 = (Path(__file__).resolve().parents[2] / "samples" / "pain001_v03.xml").read_text(encoding="utf-8")

TEXT = st.text(alphabet=st.characters(exclude_categories=("Cs",)), max_size=500)
INJECTIONS = st.sampled_from(['"', '""', "\x00", "\r", "\n", "\r\n", ",", ";", "\t", "<", ">", "&", "]]>", "﻿", "é"])
LONG_FIELD = st.integers(min_value=131073, max_value=300000)


def mutate(text, ops):
    for op, pos, extra in ops:
        if not text and op != "insert":
            continue
        i = pos % (len(text) + 1)
        if op == "drop":
            text = text[:i] + text[i + 1:]
        elif op == "duplicate":
            text = text[:i] + text[i:i + 8] + text[i:]
        elif op == "swap" and i + 1 < len(text):
            text = text[:i] + text[i + 1] + text[i] + text[i + 2:]
        elif op == "truncate":
            text = text[:i]
        elif op == "insert":
            text = text[:i] + ("X" * extra if isinstance(extra, int) else extra) + text[i:]
    return text


def ops(extras):
    op = st.tuples(st.sampled_from(["drop", "duplicate", "swap", "truncate", "insert"]),
                   st.integers(min_value=0, max_value=10_000), extras)
    return st.lists(op, min_size=1, max_size=8)


SHORT_OPS = ops(st.one_of(INJECTIONS, TEXT.filter(bool).map(lambda s: s[:20])))
LONG_OPS = ops(LONG_FIELD)

FIELD = st.one_of(
    st.sampled_from(["", " ", "T1", "1234.56.78903", "500.00", "0", "-1", "NaN", "Infinity", "1e999999", "nok",
                     "NOK", "2026-11-15", "2026-02-30", "9999-12-31", "0001-01-01", "20261115", "=1+1", "\x00"]),
    TEXT.map(lambda s: s[:40]),
)
ROWS = st.lists(st.lists(FIELD, min_size=0, max_size=9), max_size=20)


def parse(importer, text):
    try:
        return importer.parse(io.StringIO(text, newline="")), None
    except Exception as exc:
        return None, f"parse raised {type(exc).__name__}: {str(exc)[:200]}"


def transaction_problems(tx: Transaction):
    problems = []
    if not isinstance(tx.amount, Decimal) or not tx.amount.is_finite() or tx.amount <= 0:
        problems.append(f"amount {tx.amount!r}")
    if not tx.currency or tx.currency != tx.currency.upper():
        problems.append(f"currency {tx.currency!r}")
    for name in ("debtor_account", "creditor_account"):
        value = getattr(tx, name)
        if not value or " " in value or "." in value:
            problems.append(f"{name} {value!r}")
    if not tx.transaction_id or tx.transaction_id != tx.transaction_id.strip():
        problems.append(f"transaction_id {tx.transaction_id!r}")
    if not isinstance(tx.due_date, date) or (tx.created_date is not None and not isinstance(tx.created_date, date)):
        problems.append(f"dates {tx.due_date!r}/{tx.created_date!r}")
    return problems


def result_problems(result, crash):
    if crash:
        return [crash]
    if not isinstance(result, ParseResult):
        return [f"parse returned {type(result).__name__}, not ParseResult"]
    failures = []
    for err in result.errors:
        if not isinstance(err.line, int) or err.line < 0:
            failures.append(f"RowError with line {err.line!r}: {err.message!r}")
        if not str(err.message).strip():
            failures.append(f"RowError at line {err.line} with an empty message")
    for tx in result.transactions:
        problems = transaction_problems(tx)
        if problems:
            failures.append(f"invalid transaction {tx.transaction_id!r}: {', '.join(problems)}")
    return failures


def pipeline_problems(importer, text):
    with tempfile.TemporaryDirectory() as tmp:
        store = TransactionStore(os.path.join(tmp, "fuzz.db"))
        try:
            try:
                summary = import_transactions(io.StringIO(text, newline=""), importer, store,
                                              rules.evaluate, IMPORT_DATE)
            except Exception as exc:
                return [f"pipeline raised {type(exc).__name__}: {str(exc)[:200]} "
                        f"({len(store.all())} row(s) already stored)"]
            stored = len(store.all())
            if stored != summary.imported:
                return [f"store has {stored} row(s), summary.imported is {summary.imported}"]
            return []
        finally:
            store.close()


def assert_clean(failures, text):
    assert not failures, "\n".join(failures) + f"\ninput (first 300 chars): {text[:300]!r}"


@FUZZ
@given(TEXT)
def test_csv_random_text(text):
    assert_clean(result_problems(*parse(CsvImporter(), text)), text)


@FUZZ
@given(TEXT)
def test_csv_random_text_after_valid_header(text):
    text = HEADER + "\n" + text
    assert_clean(result_problems(*parse(CsvImporter(), text)), text)


@FUZZ
@given(ROWS)
def test_csv_random_rows(rows):
    buf = io.StringIO(newline="")
    buf.write(HEADER + "\r\n")
    csv.writer(buf).writerows(rows)
    text = buf.getvalue()
    assert_clean(result_problems(*parse(CsvImporter(), text)), text)


@FUZZ
@given(SHORT_OPS)
def test_csv_mutations(mutations):
    text = mutate(VALID_CSV, mutations)
    assert_clean(result_problems(*parse(CsvImporter(), text)), text)


@settings(FUZZ, max_examples=30)
@given(LONG_OPS)
def test_csv_mutations_with_very_long_fields(mutations):
    text = mutate(VALID_CSV, mutations)
    assert_clean(result_problems(*parse(CsvImporter(), text)), text)


@FUZZ
@given(SHORT_OPS)
def test_csv_mutations_through_pipeline(mutations):
    text = mutate(VALID_CSV, mutations)
    assert_clean(pipeline_problems(CsvImporter(), text), text)


@FUZZ
@given(ROWS)
def test_csv_random_rows_through_pipeline(rows):
    buf = io.StringIO(newline="")
    buf.write(HEADER + "\r\n")
    csv.writer(buf).writerows(rows)
    text = buf.getvalue()
    assert_clean(pipeline_problems(CsvImporter(), text), text)


@FUZZ
@given(st.lists(st.just(""), min_size=1, max_size=5), st.integers(min_value=0, max_value=3))
def test_csv_error_line_number_matches_physical_line(blank_lines, position):
    lines = VALID_CSV.split("\r\n")[1:-1]
    bad = "T-BAD,1234.56.78903,9876.54.32109,not-a-number,NOK,2026-11-15,2026-10-20"
    body = lines[:position] + blank_lines + [bad] + lines[position:]
    text = "\r\n".join([HEADER, *body]) + "\r\n"
    physical = text.split("\r\n").index(bad) + 1
    result, crash = parse(CsvImporter(), text)
    failures = result_problems(result, crash)
    if not failures:
        lines_reported = [e.line for e in result.errors]
        if lines_reported != [physical]:
            failures.append(f"bad row is on physical line {physical}, errors reported on {lines_reported}")
    assert_clean(failures, text)


def test_extreme_dates_through_pipeline():
    failures = []
    cases = {
        "created 9999-12-31": "X1,1234.56.78903,9876.54.32109,10.00,NOK,9999-12-31,9999-12-31",
        "created 9999-10-01": "X2,1234.56.78903,9876.54.32109,10.00,NOK,9999-12-31,9999-10-01",
        "created 0001-01-01": "X3,1234.56.78903,9876.54.32109,10.00,NOK,0001-01-01,0001-01-01",
        "due 9999-12-31": "X4,1234.56.78903,9876.54.32109,10.00,NOK,9999-12-31,",
    }
    for label, row in cases.items():
        text = HEADER + "\r\n" + row + "\r\n"
        failures += [f"{label}: {p}" for p in pipeline_problems(CsvImporter(), text)]
    assert not failures, "\n".join(failures)


@FUZZ
@given(TEXT)
def test_pain001_random_text(text):
    assert_clean(result_problems(*parse(Pain001Importer(), text)), text)


@FUZZ
@given(SHORT_OPS)
def test_pain001_mutations(mutations):
    text = mutate(VALID_PAIN001, mutations)
    assert_clean(result_problems(*parse(Pain001Importer(), text)), text)


@settings(FUZZ, max_examples=30)
@given(LONG_OPS)
def test_pain001_mutations_with_very_long_fields(mutations):
    text = mutate(VALID_PAIN001, mutations)
    assert_clean(result_problems(*parse(Pain001Importer(), text)), text)


@FUZZ
@given(SHORT_OPS)
def test_pain001_mutations_through_pipeline(mutations):
    text = mutate(VALID_PAIN001, mutations)
    assert_clean(pipeline_problems(Pain001Importer(), text), text)
