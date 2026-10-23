"""Command-line tool for trying the import pipeline locally.

    python -m fraud_detection import samples/transactions.csv
    python -m fraud_detection import samples/pain001_v03.xml
    python -m fraud_detection list
"""

import argparse
import os
import sys
from datetime import date

from . import rules
from .service import import_transactions, importer_for
from .storage import TransactionStore
from .web import DEFAULT_DB


def cmd_import(store: TransactionStore, path: str) -> int:
    rules_missing = False

    def evaluate_or_skip(tx, history, import_date):
        nonlocal rules_missing
        try:
            return rules.evaluate(tx, history, import_date)
        except NotImplementedError:
            rules_missing = True
            return []

    with open(path, newline="", encoding="utf-8-sig") as f:
        summary = import_transactions(f, importer_for(path), store, evaluate_or_skip, date.today())
    if rules_missing:
        print("NOTE: rules engine not implemented yet - transactions were imported without flags.\n")
    print(f"Imported: {summary.imported}   Flagged: {summary.flagged}   "
          f"Duplicates: {len(summary.duplicates)}   Errors: {len(summary.errors)}")
    for tid in summary.duplicates:
        print(f"  duplicate   {tid}")
    for err in summary.errors:
        print(f"  line {err.line:<5} {err.message}" if err.line else f"  error      {err.message}")
    return 1 if summary.errors else 0


def cmd_list(store: TransactionStore) -> int:
    rows = store.all()
    if not rows:
        print("No transactions stored.")
        return 0
    print(f"{'ID':<8} {'Debtor':<13} {'Creditor':<13} {'Amount':>10} {'Cur':<4} {'Due':<11} {'Created':<11} {'Imported':<11} Flags")
    for s in rows:
        t = s.transaction
        print(f"{t.transaction_id:<8} {t.debtor_account:<13} {t.creditor_account:<13} {t.amount:>10} "
              f"{t.currency:<4} {t.due_date.isoformat():<11} {(t.created_date.isoformat() if t.created_date else '-'):<11} "
              f"{s.import_date.isoformat():<11} {', '.join(s.flags) or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fraud_detection")
    parser.add_argument("--db", default=os.environ.get("FRAUD_DB", DEFAULT_DB), help="SQLite file (default: %(default)s)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_import = sub.add_parser("import", help="import a CSV or pain.001 XML file")
    p_import.add_argument("csv")
    sub.add_parser("list", help="list stored transactions")
    args = parser.parse_args(argv)

    store = TransactionStore(args.db)
    try:
        return cmd_import(store, args.csv) if args.command == "import" else cmd_list(store)
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
