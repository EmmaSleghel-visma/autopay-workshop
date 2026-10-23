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


def test_zero_and_negative_amounts_are_rejected():
    result = parse(HEADER + "t1,1,2,0.00,NOK,2026-11-30,\nt2,1,2,-5.00,NOK,2026-11-30,\nt3,1,2,0.01,NOK,2026-11-30,\n")
    assert [t.transaction_id for t in result.transactions] == ["t3"]
    assert [e.line for e in result.errors] == [2, 3]
    assert all("greater than zero" in e.message for e in result.errors)


def test_normalize_account_strips_spaces_and_dots():
    assert normalize_account(" 1234.56 78903 ") == "12345678903"


def test_row_with_more_fields_than_header_is_rejected():
    result = parse(HEADER + "t1,1,2,5.00,NOK,2026-11-30,2026-10-20,EXTRA\n")
    assert result.transactions == []
    assert result.errors[0].line == 2
    assert "more fields" in result.errors[0].message


def test_row_with_fewer_fields_than_header_is_rejected():
    result = parse(HEADER + "t1,1,2,5.00,NOK,2026-11-30\n")  # created_date column left off
    assert result.transactions == []
    assert result.errors[0].line == 2
    assert "fewer fields" in result.errors[0].message


def test_row_with_empty_optional_value_is_still_accepted():
    result = parse(HEADER + "t1,1,2,5.00,NOK,2026-11-30,\n")  # trailing comma = present but empty
    assert result.errors == []


def test_error_line_numbers_count_blank_lines():
    result = parse(HEADER + "t1,1,2,5.00,NOK,2026-11-30,\n\nt2,1,2,abc,NOK,2026-11-30,\n")
    assert [t.transaction_id for t in result.transactions] == ["t1"]
    assert [e.line for e in result.errors] == [4]


def test_oversized_field_rejects_only_that_row():
    huge = "x" * 200_000
    result = parse(HEADER + f"t1,1,2,5.00,NOK,2026-11-30,\nt2,{huge},2,5.00,NOK,2026-11-30,\nt3,1,2,5.00,NOK,2026-11-30,\n")
    assert [t.transaction_id for t in result.transactions] == ["t1", "t3"]
    assert [e.line for e in result.errors] == [3]
    assert "could not be read" in result.errors[0].message


def test_oversized_header_line_rejects_the_file_without_crash():
    result = parse("x" * 200_000 + "\nt1,1,2,5.00,NOK,2026-11-30,\n")
    assert result.transactions == []
    assert result.errors[0].line == 1
    assert "header line could not be read" in result.errors[0].message
