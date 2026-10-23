"""Transaction importers. The CSV importer is the MVP format; others can implement Importer."""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol, TextIO

from .models import ParseResult, RowError, Transaction, normalize_account

REQUIRED_COLUMNS = (
    "transaction_id",
    "debtor_account",
    "creditor_account",
    "amount",
    "currency",
    "due_date",
)
OPTIONAL_COLUMNS = ("created_date",)


class Importer(Protocol):
    def parse(self, source: TextIO) -> ParseResult: ...


class CsvImporter:
    """Comma-separated, header row required, '.' as decimal separator, dates as YYYY-MM-DD."""

    def parse(self, source: TextIO) -> ParseResult:
        result = ParseResult()
        reader = csv.DictReader(source)
        # lstrip the UTF-8 BOM that Excel puts in front of the first column name
        header = [h.lstrip("﻿").strip() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            result.errors.append(RowError(1, f"missing column(s): {', '.join(missing)}"))
            return result
        reader.fieldnames = header

        while True:
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:  # e.g. a field over the csv module's size limit
                # the failing line is not counted in line_num yet
                result.errors.append(RowError(reader.line_num + 1, f"row could not be read: {exc}"))
                continue
            try:
                result.transactions.append(self._parse_row(row))
            except ValueError as exc:
                # line_num is the physical line, so skipped blank lines still count
                result.errors.append(RowError(reader.line_num, str(exc)))
        return result

    def _parse_row(self, row: dict[str, str | None]) -> Transaction:
        if row.get(None):  # DictReader puts values beyond the header under the None key
            raise ValueError(f"more fields than the header has columns: extra {row[None]!r}")
        if any(v is None for k, v in row.items() if k is not None):  # ... and None for missing ones
            raise ValueError("fewer fields than the header has columns")
        values = {k: (v or "").strip() for k, v in row.items() if k is not None}
        empty = [c for c in REQUIRED_COLUMNS if not values.get(c)]
        if empty:
            raise ValueError(f"empty value(s): {', '.join(empty)}")
        created = values.get("created_date", "")
        return Transaction(
            transaction_id=values["transaction_id"],
            debtor_account=normalize_account(values["debtor_account"]),
            creditor_account=normalize_account(values["creditor_account"]),
            amount=_parse_amount(values["amount"]),
            currency=values["currency"].upper(),
            due_date=_parse_date("due_date", values["due_date"]),
            created_date=_parse_date("created_date", created) if created else None,
        )


def _parse_amount(raw: str) -> Decimal:
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"amount is not a number: {raw!r}") from None
    if not amount.is_finite():
        raise ValueError(f"amount is not a number: {raw!r}")
    if amount <= 0:
        raise ValueError(f"amount must be greater than zero: {raw!r}")
    return amount


def _parse_date(column: str, raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{column} is not a YYYY-MM-DD date: {raw!r}") from None
