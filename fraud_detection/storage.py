"""SQLite storage for imported transactions. Also serves as the rules engine's History."""

import json
import sqlite3
import threading
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


BUSY_TIMEOUT_SECONDS = 30  # how long a second import waits for the first one to finish


class StorageError(Exception):
    """The database file cannot be used; the message is meant for the end user."""


class TransactionStore:
    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_SECONDS, check_same_thread=False)
        try:
            self._conn.executescript(SCHEMA)
        except sqlite3.DatabaseError as exc:
            self._conn.close()
            raise StorageError(
                f"{path} is not a valid database file ({exc}). "
                "Restore your backup of it, or move it away to start with an empty database."
            ) from None
        self._in_batch = False
        # One connection is shared by the web server's threads; imports must not interleave on it.
        self._lock = threading.RLock()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def batch(self):
        """One commit for everything added inside, instead of one per row (rolled back on error).

        Takes the database write lock up front (BEGIN IMMEDIATE), so the duplicate checks made
        inside see every row a concurrent import committed; a second import waits instead.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
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
        with self._lock:  # don't read a half-finished import through the shared connection
            rows = self._conn.execute(f"{SELECT_STORED} ORDER BY seq").fetchall()
        return [_stored(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
        return row[0]

    def page(self, offset: int, limit: int) -> list[StoredTransaction]:
        """Newest first: `limit` transactions after skipping the `offset` most recent ones."""
        with self._lock:
            rows = self._conn.execute(
                f"{SELECT_STORED} ORDER BY seq DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [_stored(r) for r in rows]

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


SELECT_STORED = (
    "SELECT transaction_id, debtor_account, creditor_account, amount, currency,"
    " due_date, created_date, import_date, flags FROM transactions"
)


def _stored(r) -> StoredTransaction:
    return StoredTransaction(
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
