import io
from datetime import date
from decimal import Decimal

from fraud_detection.importer import CsvImporter
from fraud_detection.models import normalize_account

HEADER = "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date\n"


def parse(text):
    return CsvImporter().parse(io.StringIO(text))


def test_parses_valid_row():
    result = parse(HEADER + "t1,1234.56.78903,9876 54 32109,10000.01,nok,2026-11-30,2026-10-01\n")
    assert result.errors == []
    tx = result.transactions[0]
    assert tx.transaction_id == "t1"
    assert tx.debtor_account == "12345678903"
    assert tx.creditor_account == "98765432109"
    assert tx.amount == Decimal("10000.01")
    assert tx.currency == "NOK"
    assert tx.due_date == date(2026, 11, 30)
    assert tx.created_date == date(2026, 10, 1)


def test_created_date_is_optional():
    result = parse(
        "transaction_id,debtor_account,creditor_account,amount,currency,due_date\n"
        "t1,1,2,5.00,NOK,2026-11-30\n"
    )
    assert result.errors == []
    assert result.transactions[0].created_date is None


def test_utf8_bom_before_header_is_ignored():
    result = parse("﻿" + HEADER + "t1,1,2,5.00,NOK,2026-11-30,\n")
    assert result.errors == []
    assert result.transactions[0].transaction_id == "t1"


def test_missing_required_column_rejects_file():
    result = parse("transaction_id,debtor_account,amount,currency,due_date\nt1,1,5,NOK,2026-11-30\n")
    assert result.transactions == []
    assert result.errors[0].line == 1
    assert "creditor_account" in result.errors[0].message


def test_bad_rows_are_reported_with_line_numbers_and_good_rows_kept():
    result = parse(
        HEADER
        + "t1,1,2,5.00,NOK,2026-11-30,\n"
        + "t2,1,2,5,00,NOK,2026-11-30,\n"  # comma decimal separator shifts columns
        + "t3,1,2,abc,NOK,2026-11-30,\n"
        + "t4,1,2,5.00,NOK,30.11.2026,\n"
        + "t5,,2,5.00,NOK,2026-11-30,\n"
    )
    assert [t.transaction_id for t in result.transactions] == ["t1"]
    assert [e.line for e in result.errors] == [3, 4, 5, 6]


def test_normalize_account_strips_spaces_and_dots():
    assert normalize_account(" 1234.56 78903 ") == "12345678903"
