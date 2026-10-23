"""Import pipeline: parse -> skip duplicates -> evaluate rules -> store."""

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, TextIO

from .importer import Importer
from .models import History, RowError, Transaction
from .storage import TransactionStore

Evaluate = Callable[[Transaction, History, date], list[str]]


@dataclass
class ImportSummary:
    imported: int = 0
    flagged: int = 0
    duplicates: list[str] = field(default_factory=list)  # skipped transaction_ids
    errors: list[RowError] = field(default_factory=list)


def import_transactions(
    source: TextIO,
    importer: Importer,
    store: TransactionStore,
    evaluate: Evaluate,
    import_date: date,
) -> ImportSummary:
    """Rows are processed in file order, so earlier rows in the same file count as history."""
    parsed = importer.parse(source)
    summary = ImportSummary(errors=parsed.errors)
    for tx in parsed.transactions:
        if store.exists(tx.transaction_id):
            summary.duplicates.append(tx.transaction_id)
            continue
        flags = evaluate(tx, store, import_date)
        store.add(tx, import_date, flags)
        summary.imported += 1
        if flags:
            summary.flagged += 1
    return summary
