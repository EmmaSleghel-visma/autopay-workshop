"""Layer 2: the real import pipeline (CsvImporter + rules + SQLite) on all transaction files, in import order."""

from qa_support import flag_mismatches


def flags_by_id(stored):
    return {tid: list(s.flags) for tid, s in stored.items()}


def test_positive_cases_get_the_expected_flags(imported_all, expected):
    _, stored = imported_all
    failures = flag_mismatches(expected, "POS", flags_by_id(stored))
    assert not failures, "\n".join(failures)


def test_negative_cases_get_the_expected_flags(imported_all, expected):
    _, stored = imported_all
    failures = flag_mismatches(expected, "NEG", flags_by_id(stored))
    assert not failures, "\n".join(failures)


def test_corner_cases_get_the_expected_flags(imported_all, expected):
    _, stored = imported_all
    failures = flag_mismatches(expected, "CORNER", flags_by_id(stored))
    assert not failures, "\n".join(failures)


def test_import_summaries_match(imported_all, expected):
    summaries, _ = imported_all
    failures = []
    for name, exp in expected["summaries"].items():
        s = summaries[name]
        got = {"imported": s.imported, "flagged": s.flagged, "duplicates": len(s.duplicates), "errors": len(s.errors)}
        if got != exp:
            failures.append(f"{name}: expected {exp}, got {got}")
    assert not failures, "\n".join(failures)


def test_duplicates_are_reported_by_id(imported_all, expected):
    summaries, _ = imported_all
    failures = []
    for name in expected["import_order"]:
        exp = [e["transaction_id"] for e in expected["transactions"] if e["file"] == name and e["status"] == "DUPLICATE"]
        if summaries[name].duplicates != exp:
            failures.append(f"{name}: expected duplicates {exp}, got {summaries[name].duplicates}")
    assert not failures, "\n".join(failures)


def test_rejected_rows_are_reported_with_their_line_numbers(imported_all, expected):
    summaries, stored = imported_all
    rows = [e for e in expected["transactions"] if e["file"] == "errors.csv"]
    exp_lines = [line for line, e in enumerate(rows, start=2) if e["status"] == "ERROR"]
    got_lines = [err.line for err in summaries["errors.csv"].errors]
    assert got_lines == exp_lines
    leaked = [e["case"] for e in rows if e["status"] == "ERROR" and e["transaction_id"] and e["transaction_id"] in stored]
    assert not leaked, f"rejected rows were stored: {leaked}"
