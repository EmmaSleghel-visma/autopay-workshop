"""Layer 5: the command-line tool on QA files (exit codes, printed summary, no tracebacks)."""

from fraud_detection.__main__ import main
from qa_support import DATA_DIR


def run(tmp_path, *args):
    return main(["--db", str(tmp_path / "cli.db"), *args])


def test_clean_import_exits_0_and_prints_the_summary(tmp_path, capsys, expected):
    exp = expected["summaries"]["all_rules.csv"]
    assert run(tmp_path, "import", str(DATA_DIR / "all_rules.csv")) == 0
    out = capsys.readouterr().out
    assert f"Imported: {exp['imported']}" in out
    assert f"Duplicates: {exp['duplicates']}" in out
    assert "Errors: 0" in out


def test_import_with_bad_rows_exits_1_and_lists_their_lines(tmp_path, capsys, expected):
    assert run(tmp_path, "import", str(DATA_DIR / "errors.csv")) == 1
    out = capsys.readouterr().out
    rows = [e for e in expected["transactions"] if e["file"] == "errors.csv"]
    missing = [line for line, e in enumerate(rows, start=2) if e["status"] == "ERROR" and f"line {line} " not in out]
    assert not missing, f"error lines not printed: {missing}"


def test_non_csv_file_is_rejected_without_a_crash(tmp_path, capsys):
    try:
        code = run(tmp_path, "import", str(DATA_DIR / "file_not_csv.txt"))
    except Exception as exc:
        raise AssertionError(f"FILE-06: CLI crashed with {type(exc).__name__}: {exc}") from None
    assert code == 1


def test_list_shows_flags_after_import(tmp_path, capsys):
    run(tmp_path, "import", str(DATA_DIR / "all_rules.csv"))
    capsys.readouterr()
    assert run(tmp_path, "list") == 0
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("T-MIX-01"))
    assert all(code in line for code in ("HIGH_AMOUNT", "NEW_CREDITOR", "FAR_FUTURE_DUE"))
