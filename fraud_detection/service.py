"""Import pipeline: parse -> skip duplicates -> evaluate rules -> store."""

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, TextIO

from .importer import CsvImporter, Importer
from .models import History, RowError, Transaction
from .pain001 import Pain001Importer
from .storage import TransactionStore

Evaluate = Callable[[Transaction, History, date], list[str]]


def importer_for(filename: str) -> Importer:
    """Pick the importer from the file extension: .xml -> pain.001, anything else -> CSV."""
    return Pain001Importer() if filename.lower().endswith(".xml") else CsvImporter()


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
    """Rows are processed in file order, so earlier rows in the same file count as history.

    The whole file is parsed before anything is stored, and stored in one database transaction.
    """
    try:
        parsed = importer.parse(source)
    except UnicodeDecodeError as exc:
        return ImportSummary(errors=[RowError(0, f"file is not UTF-8 text (save it as CSV UTF-8): {exc.reason} at byte {exc.start}")])
    summary = ImportSummary(errors=parsed.errors)
    with store.batch():
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
