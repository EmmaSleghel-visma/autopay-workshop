"""pain.001 XML import through the real pipeline (importer_for + rules + SQLite), expectations from qa/data/pain001/expected_pain001.json."""

import json

import pytest

from fraud_detection import rules
from fraud_detection.service import import_transactions, importer_for
from qa_support import DATA_DIR, IMPORT_DATE, flag_mismatches, import_file

PAIN_DIR = DATA_DIR / "pain001"


def load(name):
    return json.loads((PAIN_DIR / name).read_text(encoding="utf-8"))


def import_xml(store, name):
    """Open and import the file the way the CLI does; an exception is returned instead of raised."""
    try:
        with open(PAIN_DIR / name, newline="", encoding="utf-8-sig") as f:
            return import_transactions(f, importer_for(name), store, rules.evaluate, IMPORT_DATE)
    except Exception as exc:
        return exc


@pytest.fixture(scope="session")
def expected_xml():
    return load("expected_pain001.json")


@pytest.fixture
def imported_xml(store, expected_xml):
    """Every step imported in order into one store: (summaries per step, stored transactions by id)."""
    summaries = [import_xml(store, s["file"]) for s in expected_xml["steps"]]
    stored = {s.transaction.transaction_id: s for s in store.all()}
    return summaries, stored


def all_entries(expected_xml):
    return {"transactions": [e for s in expected_xml["steps"] for e in s["transactions"]]}


def flags_by_id(stored):
    return {tid: list(s.flags) for tid, s in stored.items()}


def counts(summary):
    return {"imported": summary.imported, "flagged": summary.flagged,
            "duplicates": len(summary.duplicates), "errors": len(summary.errors)}


def crashes(expected_xml, summaries):
    return [f"step {i} {s['file']}: crashed with {type(got).__name__}: {got}"
            for i, (s, got) in enumerate(zip(expected_xml["steps"], summaries), start=1) if isinstance(got, Exception)]


def test_positive_cases_get_the_expected_flags(imported_xml, expected_xml):
    _, stored = imported_xml
    failures = flag_mismatches(all_entries(expected_xml), "POS", flags_by_id(stored))
    assert not failures, "\n".join(failures)


def test_negative_cases_get_the_expected_flags(imported_xml, expected_xml):
    _, stored = imported_xml
    failures = flag_mismatches(all_entries(expected_xml), "NEG", flags_by_id(stored))
    assert not failures, "\n".join(failures)


def test_corner_cases_get_the_expected_flags(imported_xml, expected_xml):
    _, stored = imported_xml
    failures = flag_mismatches(all_entries(expected_xml), "CORNER", flags_by_id(stored))
    assert not failures, "\n".join(failures)


def test_import_summaries_match_per_file(imported_xml, expected_xml):
    summaries, _ = imported_xml
    failures = crashes(expected_xml, summaries)
    for i, (s, got) in enumerate(zip(expected_xml["steps"], summaries), start=1):
        if not isinstance(got, Exception) and counts(got) != s["summary"]:
            failures.append(f"step {i} {s['case']} {s['file']}: expected {s['summary']}, got {counts(got)} ({s['note']})")
    assert not failures, "\n".join(failures)


def test_duplicates_are_reported_by_id(imported_xml, expected_xml):
    summaries, _ = imported_xml
    failures = []
    for i, (s, got) in enumerate(zip(expected_xml["steps"], summaries), start=1):
        if not isinstance(got, Exception) and got.duplicates != s["duplicates"]:
            failures.append(f"step {i} {s['case']} {s['file']}: expected duplicates {s['duplicates']}, got {got.duplicates}")
    assert not failures, "\n".join(failures)


def test_rejected_transactions_are_reported_and_not_stored(imported_xml, expected_xml):
    summaries, stored = imported_xml
    failures = []
    for s, got in zip(expected_xml["steps"], summaries):
        if isinstance(got, Exception):
            continue
        messages = [e.message for e in got.errors]
        for e in s["transactions"]:
            if e["status"] != "ERROR":
                continue
            if not any(all(part in m for part in e["error_contains"]) for m in messages):
                failures.append(f"{e['case']}: no error naming {e['error_contains']} in {messages} ({e['note']})")
            if e["transaction_id"] and e["transaction_id"] in stored:
                failures.append(f"{e['case']} {e['transaction_id']}: rejected but stored ({e['note']})")
    assert not failures, "\n".join(failures)


def test_whole_file_rejections(imported_xml, expected_xml):
    summaries, stored = imported_xml
    failures = []
    for s, got in zip(expected_xml["steps"], summaries):
        if not s["rejected"]:
            continue
        if isinstance(got, Exception):
            failures.append(f"{s['case']} {s['file']}: crashed with {type(got).__name__}: {got} ({s['note']})")
            continue
        if got.imported or len(got.errors) != 1:
            failures.append(f"{s['case']} {s['file']}: expected 0 imported and 1 error, got {counts(got)} "
                            f"{[e.message for e in got.errors]} ({s['note']})")
        elif s["file_error"] and s["file_error"] not in got.errors[0].message:
            failures.append(f"{s['case']} {s['file']}: expected error containing {s['file_error']!r}, got {got.errors[0].message!r}")
    leaked = sorted(tid for tid, st in stored.items() if tid.startswith(("DTD-", "XXE-", "UNK-")))
    if leaked:
        failures.append(f"transactions from refused files were stored: {leaked}")
    assert not failures, "\n".join(failures)


def test_stored_fields_follow_the_pain001_mapping(imported_xml, expected_xml):
    _, stored = imported_xml
    failures = []
    for s in expected_xml["steps"]:
        for e in s["transactions"]:
            if e["status"] != "IMPORTED" or e["transaction_id"] not in stored:
                continue
            t = stored[e["transaction_id"]].transaction
            got = {"debtor_account": t.debtor_account, "creditor_account": t.creditor_account, "amount": str(t.amount),
                   "currency": t.currency, "due_date": t.due_date.isoformat(),
                   "created_date": t.created_date.isoformat() if t.created_date else None}
            diff = {k: (v, got[k]) for k, v in e["fields"].items() if got[k] != v}
            if diff:
                failures.append(f"{e['case']} {e['transaction_id']}: (expected, got) {diff}")
    assert not failures, "\n".join(failures)


def test_customer_sample_v03(store):
    exp = load("customer_sample_v03.expected.json")
    got = import_xml(store, "customer_sample_v03.xml")
    assert not isinstance(got, Exception), f"import crashed: {got!r}"
    failures = []
    if counts(got) != exp["summary"]:
        failures.append(f"summary: expected {exp['summary']}, got {counts(got)}")
    flags = {s.transaction.transaction_id: sorted(s.flags) for s in store.all()}
    for e in exp["transactions"]:
        if flags.get(e["transaction_id"]) != sorted(e["flags"]):
            failures.append(f"{e['transaction_id']}: expected {sorted(e['flags'])}, got {flags.get(e['transaction_id'])} ({e['note']})")
    assert not failures, "\n".join(failures)


def test_history_is_shared_between_csv_and_xml_imports(store, expected_xml):
    cross = expected_xml["cross_format"]
    import_file(store, cross["after_csv"])
    got = import_xml(store, cross["file"])
    assert not isinstance(got, Exception), f"import crashed: {got!r}"
    failures = []
    if counts(got) != cross["summary"]:
        failures.append(f"summary: expected {cross['summary']}, got {counts(got)}")
    if got.duplicates != cross["duplicates"]:
        failures.append(f"duplicates: expected {cross['duplicates']}, got {got.duplicates}")
    stored = {s.transaction.transaction_id: s for s in store.all()}
    for e in cross["transactions"]:
        if e["status"] != "IMPORTED":
            continue
        got_flags = sorted(stored[e["transaction_id"]].flags) if e["transaction_id"] in stored else None
        if got_flags != e["flags"]:
            failures.append(f"{e['case']} {e['transaction_id']}: expected {e['flags']}, got {got_flags} ({e['note']})")
    assert not failures, "\n".join(failures)
