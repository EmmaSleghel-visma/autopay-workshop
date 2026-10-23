"""Core data types shared by the importer, storage, rules and web layers."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol


def normalize_account(raw: str) -> str:
    """Strip spaces and dots so '1234.56.78903' and '1234 56 78903' compare equal."""
    return raw.replace(" ", "").replace(".", "").strip()


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    debtor_account: str  # normalized
    creditor_account: str  # normalized
    amount: Decimal
    currency: str  # upper-case ISO code, e.g. "NOK"
    due_date: date
    created_date: date | None = None


@dataclass(frozen=True)
class StoredTransaction:
    transaction: Transaction
    import_date: date
    flags: tuple[str, ...]


@dataclass
class RowError:
    line: int  # 1-based line number in the source file, header is line 1
    message: str


@dataclass
class ParseResult:
    transactions: list[Transaction] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


class History(Protocol):
    """What the rules engine may ask about earlier transactions."""

    def debtor_known(self, debtor_account: str) -> bool: ...

    def has_paid(self, debtor_account: str, creditor_account: str) -> bool: ...
