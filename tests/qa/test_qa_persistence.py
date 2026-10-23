"""Layer 4: data survives a restart, and ids imported before a restart still count as duplicates."""

from fraud_detection.storage import TransactionStore
from qa_support import import_file


def test_transactions_and_flags_survive_a_restart(tmp_path, expected):
    db = tmp_path / "restart.db"
    store = TransactionStore(db)
    for name in expected["import_order"]:
        import_file(store, name)
    before = store.all()
    store.close()

    reopened = TransactionStore(db)
    try:
        assert reopened.all() == before
        assert len(before) == sum(s["imported"] for s in expected["summaries"].values())
    finally:
        reopened.close()


def test_reimport_after_restart_is_all_duplicates(tmp_path, expected):
    db = tmp_path / "restart.db"
    store = TransactionStore(db)
    import_file(store, "all_rules.csv")
    store.close()

    reopened = TransactionStore(db)
    try:
        s = import_file(reopened, "all_rules.csv")
        rows = [e for e in expected["transactions"] if e["file"] == "all_rules.csv"]
        assert (s.imported, s.flagged, len(s.duplicates)) == (0, 0, len(rows))
    finally:
        reopened.close()
