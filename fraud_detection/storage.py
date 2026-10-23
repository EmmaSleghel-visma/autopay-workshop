"""SQLite storage for imported transactions. Also serves as the rules engine's History."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import StoredTransaction, Transaction

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    seq              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id   TEXT NOT NULL UNIQUE,
    debtor_account   TEXT NOT NULL,
    creditor_account TEXT NOT NULL,
    amount           TEXT NOT NULL,
    currency         TEXT NOT NULL,
    due_date         TEXT NOT NULL,
    created_date     TEXT,
    import_date      TEXT NOT NULL,
    flags            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_debtor_creditor ON transactions (debtor_account, creditor_account);
"""


class TransactionStore:
    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._in_batch = False

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def batch(self):
        """One commit for everything added inside, instead of one per row (rolled back on error)."""
        self._in_batch = True
        try:
            with self._conn:
                yield
        finally:
            self._in_batch = False

    def exists(self, transaction_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM transactions WHERE transaction_id = ?", (transaction_id,)
        ).fetchone()
        return row is not None

    def add(self, tx: Transaction, import_date: date, flags: list[str]) -> None:
        self._conn.execute(
            "INSERT INTO transactions (transaction_id, debtor_account, creditor_account,"
            " amount, currency, due_date, created_date, import_date, flags)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tx.transaction_id,
                tx.debtor_account,
                tx.creditor_account,
                str(tx.amount),
                tx.currency,
                tx.due_date.isoformat(),
                tx.created_date.isoformat() if tx.created_date else None,
                import_date.isoformat(),
                json.dumps(flags),
            ),
        )
        if not self._in_batch:
            self._conn.commit()

    def all(self) -> list[StoredTransaction]:
        rows = self._conn.execute(
            "SELECT transaction_id, debtor_account, creditor_account, amount, currency,"
            " due_date, created_date, import_date, flags FROM transactions ORDER BY seq"
        ).fetchall()
        return [
            StoredTransaction(
                transaction=Transaction(
                    transaction_id=r[0],
                    debtor_account=r[1],
                    creditor_account=r[2],
                    amount=Decimal(r[3]),
                    currency=r[4],
                    due_date=date.fromisoformat(r[5]),
                    created_date=date.fromisoformat(r[6]) if r[6] else None,
                ),
                import_date=date.fromisoformat(r[7]),
                flags=tuple(json.loads(r[8])),
            )
            for r in rows
        ]

    # History protocol

    def debtor_known(self, debtor_account: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM transactions WHERE debtor_account = ? LIMIT 1", (debtor_account,)
        ).fetchone()
        return row is not None

    def has_paid(self, debtor_account: str, creditor_account: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM transactions WHERE debtor_account = ? AND creditor_account = ? LIMIT 1",
            (debtor_account, creditor_account),
        ).fetchone()
        return row is not None
