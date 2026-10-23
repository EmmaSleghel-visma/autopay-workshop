"""Paths, import helper and soft-assertion helper shared by the QA tests."""

import json
from datetime import date
from pathlib import Path

from fraud_detection import rules
from fraud_detection.service import import_transactions, importer_for

QA_DIR = Path(__file__).resolve().parents[2] / "qa"
DATA_DIR = QA_DIR / "data"
IMPORT_DATE = date(2026, 10, 23)


def load_expected():
    return json.loads((QA_DIR / "expected.json").read_text(encoding="utf-8"))


def import_file(store, name):
    with open(DATA_DIR / name, newline="", encoding="utf-8-sig") as f:
        return import_transactions(f, importer_for(name), store, rules.evaluate, IMPORT_DATE)


def flag_mismatches(expected, category, actual_flags):
    """One line per imported case of the category whose flags differ; actual_flags maps id -> flags or None."""
    failures = []
    for e in expected["transactions"]:
        if e["category"] != category or e["status"] != "IMPORTED":
            continue
        got = actual_flags.get(e["transaction_id"])
        if got is None:
            failures.append(f"{e['case']} {e['transaction_id']}: not imported ({e['note']})")
        elif sorted(got) != e["flags"]:
            failures.append(f"{e['case']} {e['transaction_id']}: expected {e['flags'] or 'no flags'}, "
                            f"got {sorted(got) or 'no flags'} ({e['note']})")
    return failures
