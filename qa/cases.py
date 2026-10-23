"""Single source of truth for the Fraud Detection MVP test data.

Running this file writes:
  data/all_rules.csv         rule cases (positive, negative, corner) in one import
  data/import2_followup.csv  second import (cross-import R2 and duplicates)
  data/errors.csv            malformed rows (import summary: errors)
  data/file_*.csv / .txt     whole-file negative and corner cases
  expected.json              expected flags / status per transaction id, plus file-level expectations

Every case has a category:
  POS     valid, everyday input; the app does what it should (flag fires, clean txn passes)
  NEG     invalid or hostile input, or input that must NOT trigger a rule
  CORNER  boundaries and unusual-but-valid input

Assumed CSV columns (confirm with Developer):
  transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date
Dates are ISO yyyy-mm-dd, amount uses a dot decimal separator.
Rows are listed in import order; R2 depends on that order.
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).parent
HEADER = ["transaction_id", "debtor_account", "creditor_account", "amount", "currency", "due_date", "created_date"]

R1 = "HIGH_AMOUNT"
R2 = "NEW_CREDITOR"
R3 = "FAR_FUTURE_DUE"
CUR = "UNSUPPORTED_CURRENCY"
PAST = "PAST_DUE_DATE"
POS, NEG, CORNER = "POS", "NEG", "CORNER"

D_BASE = "1234.56.78901"
D_R2 = "2000.11.22222"
D_FMT = "3000.11.33333"
D_CROSS = "4000.11.44444"
D_POS = "5000.11.55555"
C_A = "9000.11.00001"
C_B = "9000.11.00002"
C_C = "9000.11.00003"


def row(tid, debtor, creditor, amount, due, created="2026-10-01", currency="NOK"):
    return [tid, debtor, creditor, amount, currency, due, created]


# (row, expected flags or status, case id, category, note).
# Debtor D_BASE only ever pays C_A, so it never trips R2 and isolates R1/R3/currency cases.
IMPORT1 = [
    # Positive: everyday transactions
    (row("T-POS-01", D_POS, C_A, "1500.00", "2026-10-15"), [], "POS-01", POS, "typical small payment, debtor's first: clean"),
    (row("T-POS-02", D_POS, C_A, "2300.50", "2026-11-01"), [], "POS-02", POS, "known creditor, normal amount and due date: clean"),
    (row("T-POS-03", D_POS, C_A, "75000.00", "2026-10-20"), [R1], "POS-03", POS, "clearly large amount"),
    (row("T-POS-04", D_POS, C_B, "800.00", "2026-10-20"), [R2], "POS-04", POS, "known debtor pays a new creditor"),
    (row("T-POS-05", D_POS, C_A, "800.00", "2027-04-01"), [R3], "POS-05", POS, "due 6 months out"),

    # R1 amount
    (row("T-R1-01", D_BASE, C_A, "10000.00", "2026-10-15"), [], "R1-01", CORNER, "exactly 10,000.00 is not flagged"),
    (row("T-R1-02", D_BASE, C_A, "10000.01", "2026-10-15"), [R1], "R1-02", CORNER, "one ore over the limit"),
    (row("T-R1-03", D_BASE, C_A, "9999.99", "2026-10-15"), [], "R1-03", CORNER, "one ore under"),
    (row("T-R1-04", D_BASE, C_A, "250000", "2026-10-15"), [R1], "R1-04", POS, "large amount without decimals"),
    (row("T-R1-05", D_BASE, C_A, "0.01", "2026-10-15"), [], "R1-05", CORNER, "smallest amount"),
    (row("T-R1-06", D_BASE, C_A, "10000.0", "2026-10-15"), [], "R1-06", CORNER, "one decimal, equal to limit"),
    (row("T-R1-07", D_BASE, C_A, "010000.00", "2026-10-15"), [], "R1-07", CORNER, "leading zero, equal to limit"),
    (row("T-R1-08", D_BASE, C_A, "99999999.99", "2026-10-15"), [R1], "R1-08", CORNER, "very large amount, no overflow"),
    (row("T-R1-09", D_BASE, C_A, "5000.00", "2026-10-15"), [], "R1-09", NEG, "ordinary amount must not trip R1"),

    # R3 due date vs created_date + 3 calendar months
    (row("T-R3-01", D_BASE, C_A, "100.00", "2027-01-01", "2026-10-01"), [], "R3-01", CORNER, "exactly 3 months is not flagged"),
    (row("T-R3-02", D_BASE, C_A, "100.00", "2027-01-02", "2026-10-01"), [R3], "R3-02", CORNER, "3 months + 1 day"),
    (row("T-R3-03", D_BASE, C_A, "100.00", "2026-04-30", "2026-01-31"), [], "R3-03", CORNER, "month end: Jan 31 + 3m = Apr 30 (PO: last day of month)"),
    (row("T-R3-04", D_BASE, C_A, "100.00", "2026-05-01", "2026-01-31"), [R3], "R3-04", CORNER, "month end + 1 day"),
    (row("T-R3-05", D_BASE, C_A, "100.00", "2026-02-28", "2025-11-30"), [], "R3-05", CORNER, "Nov 30 + 3m = Feb 28 (non-leap)"),
    (row("T-R3-06", D_BASE, C_A, "100.00", "2026-03-01", "2025-11-30"), [R3], "R3-06", CORNER, "Feb 28 + 1 day"),
    (row("T-R3-07", D_BASE, C_A, "100.00", "2028-02-29", "2027-11-29"), [], "R3-07", CORNER, "leap year: Nov 29 + 3m = Feb 29"),
    (row("T-R3-08", D_BASE, C_A, "100.00", "2026-09-01", "2026-10-01"), [PAST], "R3-08", NEG, "due date before created date: PAST_DUE_DATE, row kept (PO)"),
    (row("T-R3-16", D_BASE, C_A, "100.00", "2026-10-22", ""), [PAST], "R3-16", CORNER, "no created_date, due the day before import date: PAST_DUE_DATE"),
    (row("T-R3-17", D_BASE, C_A, "100.00", "2026-09-30", "2026-10-01"), [PAST], "R3-17", CORNER, "due one day before created date: PAST_DUE_DATE"),
    (row("T-R3-09", D_BASE, C_A, "100.00", "2099-12-31", ""), [R3], "R3-09", POS, "no created_date: compared to import date"),
    (row("T-R3-10", D_BASE, C_A, "100.00", "2026-10-23", ""), [], "R3-10", CORNER, "no created_date, due on import date"),
    (row("T-R3-11", D_BASE, C_A, "100.00", "2026-10-01", "2026-10-01"), [], "R3-11", CORNER, "due date equals created date"),
    (row("T-R3-12", D_BASE, C_A, "100.00", "2027-02-28", "2026-11-30"), [], "R3-12", CORNER, "crosses year end: Nov 30 + 3m = Feb 28"),
    (row("T-R3-13", D_BASE, C_A, "100.00", "2027-03-01", "2026-11-30"), [R3], "R3-13", CORNER, "crosses year end + 1 day"),
    (row("T-R3-14", D_BASE, C_A, "100.00", "2028-05-29", "2028-02-29"), [], "R3-14", CORNER, "from leap day: Feb 29 + 3m = May 29"),
    (row("T-R3-15", D_BASE, C_A, "100.00", "2026-12-01", "2026-10-01"), [], "R3-15", NEG, "2 months out must not trip R3"),

    # R2 new creditor for a known debtor (order matters)
    (row("T-R2-01", D_R2, C_A, "100.00", "2026-10-15"), [], "R2-01", NEG, "debtor's first txn is never flagged"),
    (row("T-R2-02", D_R2, C_A, "100.00", "2026-10-15"), [], "R2-02", NEG, "same creditor again"),
    (row("T-R2-03", D_R2, C_B, "100.00", "2026-10-15"), [R2], "R2-03", POS, "A then B: B is new"),
    (row("T-R2-04", D_R2, C_B, "100.00", "2026-10-15"), [], "R2-04", CORNER, "B now known (confirm)"),
    (row("T-R2-05", D_R2, "9000 11 00001", "100.00", "2026-10-15"), [], "R2-05", CORNER, "C_A with spaces instead of dots = same account"),
    (row("T-R2-06", D_R2, "90001100001", "100.00", "2026-10-15"), [], "R2-06", CORNER, "C_A without separators = same account"),
    (row("T-R2-07", "2000 11 22222", C_C, "100.00", "2026-10-15"), [R2], "R2-07", CORNER, "debtor written with spaces is still known; C_C is new"),
    (row("T-R2-08", D_R2, " 9000.11.00001 ", "100.00", "2026-10-15"), [], "R2-08", CORNER, "leading/trailing whitespace around a known account (confirm)"),
    (row("T-R2-09", C_A, D_R2, "100.00", "2026-10-15"), [], "R2-09", CORNER, "roles swapped: C_A as debtor is a new debtor, first txn"),

    # Normalisation must not merge different accounts
    (row("T-FMT-01", D_FMT, "1111.22.33333", "100.00", "2026-10-15"), [], "FMT-01", NEG, "debtor first txn"),
    (row("T-FMT-02", D_FMT, "1111.22.33334", "100.00", "2026-10-15"), [R2], "FMT-02", NEG, "differs in last digit: different creditor"),

    # Combined rules
    (row("T-MIX-01", D_R2, "9000.11.00099", "50000.00", "2027-06-01", "2026-10-01"), [R1, R2, R3], "MIX-01", POS, "all three rules on one txn"),
    (row("T-MIX-02", D_BASE, C_A, "20000.00", "2027-06-01", "2026-10-01"), [R1, R3], "MIX-02", POS, "two rules on one txn"),

    # Currency
    (row("T-CUR-01", D_BASE, C_A, "100.00", "2026-10-15", currency="EUR"), [CUR], "CUR-01", NEG, "non-NOK"),
    (row("T-CUR-02", D_BASE, C_A, "50000.00", "2026-10-15", currency="SEK"), [CUR, R1], "CUR-02", NEG, "non-NOK over limit: other rules still apply (PO)"),
    (row("T-CUR-05", D_POS, C_C, "100.00", "2027-06-01", currency="EUR"), [CUR, R2, R3], "CUR-05", NEG, "non-NOK + new creditor + far due: all flags (PO)"),
    (row("T-CUR-03", D_BASE, C_A, "100.00", "2026-10-15", currency="nok"), [], "CUR-03", CORNER, "lowercase nok accepted as NOK (confirm)"),
    (row("T-CUR-04", D_BASE, C_A, "100.00", "2026-10-15", currency=" NOK "), [], "CUR-04", CORNER, "padded NOK accepted (confirm)"),

    # Cross-import R2 seed
    (row("T-X-01", D_CROSS, C_A, "100.00", "2026-10-15"), [], "XIMP-01", POS, "debtor first seen in import 1"),

    # Hostile text must be stored and shown as plain text
    (row("T-XSS-01", "<script>alert(1)</script>", C_A, "100.00", "2026-10-15"), [], "XSS-01", NEG, "HTML in account field: shown escaped on the web page (confirm: or rejected)"),

    # Duplicate inside the same file: second one skipped and reported
    (row("T-DUP-01", D_BASE, C_A, "100.00", "2026-10-15"), [], "DUP-01", POS, "first occurrence kept"),
    (row("T-DUP-01", D_BASE, C_A, "99999.00", "2026-10-15"), "DUPLICATE", "DUP-02", NEG, "same id in same file: skipped, not flagged R1"),
]

IMPORT2 = [
    (row("T-X-02", D_CROSS, C_B, "100.00", "2026-10-15"), [R2], "XIMP-02", POS, "new creditor for a debtor known from an earlier import"),
    (row("T-X-03", D_CROSS, C_A, "100.00", "2026-10-15"), [], "XIMP-03", POS, "creditor known from earlier import"),
    (row("T-R1-02", D_BASE, C_A, "100.00", "2026-10-15"), "DUPLICATE", "DUP-03", NEG, "id already imported earlier: skipped"),
    (row("t-r1-03", D_BASE, C_A, "100.00", "2026-10-15"), [], "DUP-04", CORNER, "same id in other case: treated as a new id (confirm)"),
]

ERRORS = [
    (["T-ERR-01", D_BASE, C_A, "abc", "NOK", "2026-10-15", "2026-10-01"], "ERROR", "ERR-01", NEG, "non-numeric amount"),
    (["T-ERR-02", D_BASE, C_A, "", "NOK", "2026-10-15", "2026-10-01"], "ERROR", "ERR-02", NEG, "missing amount"),
    (["T-ERR-03", D_BASE, C_A, "100.00", "NOK", "15/10/2026", "2026-10-01"], "ERROR", "ERR-03", NEG, "wrong date format"),
    (["T-ERR-04", D_BASE, C_A, "100.00", "NOK", "2026-02-30", "2026-10-01"], "ERROR", "ERR-04", NEG, "impossible date"),
    (["T-ERR-05", "", C_A, "100.00", "NOK", "2026-10-15", "2026-10-01"], "ERROR", "ERR-05", NEG, "missing debtor"),
    (["", D_BASE, C_A, "100.00", "NOK", "2026-10-15", "2026-10-01"], "ERROR", "ERR-06", NEG, "missing transaction id"),
    (["T-ERR-07", D_BASE, C_A, "-500.00", "NOK", "2026-10-15", "2026-10-01"], "ERROR", "ERR-07", NEG, "negative amount: rejected (PO)"),
    (["T-ERR-08", D_BASE, C_A, "100.00", "", "2026-10-15", "2026-10-01"], "ERROR", "ERR-08", NEG, "missing currency"),
    (["T-ERR-09", D_BASE, "", "100.00", "NOK", "2026-10-15", "2026-10-01"], "ERROR", "ERR-09", NEG, "missing creditor"),
    (["T-ERR-10", D_BASE, C_A, "100.00", "NOK", "", "2026-10-01"], "ERROR", "ERR-10", NEG, "missing due date"),
    (["T-ERR-11", D_BASE, C_A, "10000,50", "NOK", "2026-10-15", "2026-10-01"], "ERROR", "ERR-11", NEG, "comma decimal separator (confirm: error or 10000.50?)"),
    (["T-ERR-12", D_BASE, C_A, "0.00", "NOK", "2026-10-15", "2026-10-01"], "ERROR", "ERR-12", CORNER, "zero amount: rejected (PO)"),
    (["T-ERR-13", D_BASE, C_A, "100.00", "NOK", "2026-10-15"], "ERROR", "ERR-13", NEG, "row with fewer values than the header: rejected (PO 10:08)"),
    (["T-ERR-14", D_BASE, C_A, "100.00", "NOK", "2026-10-15", "2026-10-01", "extra"], "ERROR", "ERR-14", NEG, "row with more values than the header: rejected (PO 10:08)"),
    (["T-ERR-15", D_BASE, C_A, "   ", "NOK", "2026-10-15", "2026-10-01"], "ERROR", "ERR-15", NEG, "whitespace-only amount"),
    (["T-OK-01", D_BASE, C_A, "100.00", "NOK", "2026-10-15", "2026-10-01"], [], "ERR-OK", POS, "valid row among bad ones is still imported"),
]

GOOD_ROW = row("T-FILE-01", D_BASE, C_A, "100.00", "2026-10-15")

# (file name, raw bytes, case id, category, expected behaviour, imported, errors)
FILES = [
    ("file_empty.csv", ",".join(HEADER).encode() + b"\r\n", "FILE-01", CORNER, "header only: summary 0/0/0/0, no crash", 0, 0),
    ("file_zero_bytes.csv", b"", "FILE-02", NEG, "0-byte file: clear error, no crash", 0, 1),
    ("file_bad_header.csv", b"id,from,to,sum,ccy,due,created\r\n" + ",".join(GOOD_ROW).encode() + b"\r\n", "FILE-03", NEG, "unknown header: whole file rejected with a clear message", 0, 1),
    ("file_no_header.csv", ",".join(GOOD_ROW).encode() + b"\r\n", "FILE-04", NEG, "missing header row: rejected (or first row not silently lost)", 0, 1),
    ("file_semicolon.csv", ";".join(HEADER).encode() + b"\r\n" + ";".join(GOOD_ROW).encode() + b"\r\n", "FILE-05", NEG, "semicolon delimiter (Excel NO locale): clear error or supported (confirm)", 0, 1),
    ("file_not_csv.txt", b"\x89PNG\r\n\x1a\n\x00\x00binary", "FILE-06", NEG, "binary / non-CSV upload: rejected, no crash", 0, 1),
    ("file_bom.csv", b"\xef\xbb\xbf" + ",".join(HEADER).encode() + b"\r\n" + ",".join(GOOD_ROW).encode() + b"\r\n", "FILE-07", CORNER, "UTF-8 BOM (Excel export): first column still recognised, 1 imported", 1, 0),
    ("file_lf_endings.csv", ",".join(HEADER).encode() + b"\n" + ",".join(GOOD_ROW).encode() + b"\n", "FILE-08", CORNER, "Unix line endings: 1 imported", 1, 0),
    ("file_reordered_columns.csv", b"amount,transaction_id,currency,debtor_account,creditor_account,due_date,created_date\r\n100.00,T-FILE-01,NOK,"
     + D_BASE.encode() + b"," + C_A.encode() + b",2026-10-15,2026-10-01\r\n", "FILE-09", CORNER, "columns in another order: read by name, 1 imported (confirm)", 1, 0),
    ("file_trailing_blank_lines.csv", ",".join(HEADER).encode() + b"\r\n" + ",".join(GOOD_ROW).encode() + b"\r\n\r\n\r\n", "FILE-10", CORNER, "blank lines at the end: not counted as errors", 1, 0),
    ("file_quoted_fields.csv", ",".join(HEADER).encode() + b'\r\n"T-FILE-01","' + D_BASE.encode() + b'","' + C_A.encode()
     + b'","100.00","NOK","2026-10-15","2026-10-01"\r\n', "FILE-11", CORNER, "all fields quoted: 1 imported", 1, 0),
]


def write(name, cases):
    with open(HERE / "data" / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for r, *_ in cases:
            w.writerow(r)


def write_large(name, rows):
    with open(HERE / "data" / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i in range(rows):
            w.writerow(row(f"T-BULK-{i:05d}", f"6000.11.{i % 500:05d}", f"7000.11.{i % 37:05d}", f"{(i * 37) % 20000 + 1}.{i % 100:02d}", "2026-11-15"))


def expected(cases, file):
    out = []
    for r, exp, cid, cat, note in cases:
        status = exp if isinstance(exp, str) else "IMPORTED"
        out.append({"file": file, "case": cid, "category": cat, "transaction_id": r[0], "status": status,
                    "flags": sorted(exp) if isinstance(exp, list) else [], "note": note})
    return out


def summary(cases):
    statuses = [e if isinstance(e, str) else "IMPORTED" for _, e, *_ in cases]
    return {"imported": statuses.count("IMPORTED"),
            "flagged": sum(1 for _, e, *_ in cases if isinstance(e, list) and e),
            "duplicates": statuses.count("DUPLICATE"),
            "errors": statuses.count("ERROR")}


if __name__ == "__main__":
    (HERE / "data").mkdir(exist_ok=True)
    write("all_rules.csv", IMPORT1)
    write("import2_followup.csv", IMPORT2)
    write("errors.csv", ERRORS)
    write_large("file_large_10k.csv", 10000)
    for name, content, *_ in FILES:
        (HERE / "data" / name).write_bytes(content)
    transactions = expected(IMPORT1, "all_rules.csv") + expected(IMPORT2, "import2_followup.csv") + expected(ERRORS, "errors.csv")
    files = [{"file": n, "case": c, "category": cat, "expect": e, "imported": imp, "errors": err} for n, _, c, cat, e, imp, err in FILES]
    files.append({"file": "file_large_10k.csv", "case": "FILE-12", "category": CORNER,
                  "expect": "10,000 rows import in reasonable time (< 30 s), page stays usable", "imported": 10000, "errors": 0})
    result = {
        "import_order": ["all_rules.csv", "import2_followup.csv", "errors.csv"],
        "summaries": {"all_rules.csv": summary(IMPORT1), "import2_followup.csv": summary(IMPORT2),
                      "errors.csv": summary(ERRORS)},
        "transactions": transactions,
        "files": files,
    }
    (HERE / "expected.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    counts = {}
    for c in transactions + files:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    print(json.dumps({"summaries": result["summaries"], "cases_by_category": counts, "total": sum(counts.values())}, indent=2))
