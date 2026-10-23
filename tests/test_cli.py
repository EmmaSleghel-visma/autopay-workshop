from pathlib import Path

from fraud_detection.__main__ import main

SAMPLE = Path(__file__).parent.parent / "samples" / "transactions.csv"


def test_sample_file_imports_with_documented_totals(tmp_path, capsys):
    db = str(tmp_path / "fraud.db")
    assert main(["--db", db, "import", str(SAMPLE)]) == 1  # sample has 2 bad rows on purpose
    out = capsys.readouterr().out
    assert "Imported: 10" in out
    assert "Duplicates: 1" in out
    assert "Errors: 2" in out
    assert "line 13" in out and "line 14" in out


def test_list_shows_imported_transactions(tmp_path, capsys):
    db = str(tmp_path / "fraud.db")
    main(["--db", db, "import", str(SAMPLE)])
    capsys.readouterr()
    assert main(["--db", db, "list"]) == 0
    out = capsys.readouterr().out
    assert "T010" in out and "25000.00" in out
