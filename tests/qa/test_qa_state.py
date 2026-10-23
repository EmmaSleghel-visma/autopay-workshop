"""Layer 6: state and history - import order, concurrent imports, interrupted imports, old databases, history across formats."""

import itertools
import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from fraud_detection import rules
from fraud_detection.service import import_transactions, importer_for
from fraud_detection.storage import TransactionStore
from qa_support import IMPORT_DATE

REPO_ROOT = Path(__file__).resolve().parents[2]
HEADER = "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date"
NON_ORDER_FLAGS = ("HIGH_AMOUNT", "FAR_FUTURE_DUE", "PAST_DUE_DATE", "UNSUPPORTED_CURRENCY")
TOTAL_BIG = 60000
SUMMARY_RE = re.compile(r"Imported: (\d+)\s+Flagged: (\d+)\s+Duplicates: (\d+)\s+Errors: (\d+)")


def write_csv(path, rows):
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


def import_path(store, path, evaluate=rules.evaluate):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return import_transactions(f, importer_for(path.name), store, evaluate, IMPORT_DATE)


def big_csv(path, count, prefix="T", start=0):
    rows = [f"{prefix}{i:06d},D{i % 500:03d},C{i % 7:03d},100.00,NOK,2026-11-01,2026-10-20"
            for i in range(start, start + count)]
    return write_csv(path, rows)


def run_cli(db, *args):
    return subprocess.Popen([sys.executable, "-m", "fraud_detection", "--db", str(db), *args],
                            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def finish(proc, timeout=120):
    out, err = proc.communicate(timeout=timeout)
    match = SUMMARY_RE.search(out)
    summary = tuple(int(g) for g in match.groups()) if match else None
    return proc.returncode, out, err, summary


def raw_rows(db):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute("SELECT transaction_id, flags, amount, due_date FROM transactions").fetchall()
    finally:
        conn.close()


def row_problems(rows):
    problems = []
    for tid, flags, amount, due in rows:
        try:
            parsed = json.loads(flags)
            if not isinstance(parsed, list) or any(f not in (*NON_ORDER_FLAGS, "NEW_CREDITOR") for f in parsed):
                problems.append(f"{tid}: flags not a list of known codes: {flags!r}")
        except (TypeError, ValueError):
            problems.append(f"{tid}: flags not valid JSON: {flags!r}")
        if not amount or not due:
            problems.append(f"{tid}: half-written row (amount={amount!r}, due={due!r})")
    ids = [r[0] for r in rows]
    if len(ids) != len(set(ids)):
        problems.append(f"transaction ids stored more than once: {sorted({i for i in ids if ids.count(i) > 1})}")
    return problems


def order_files(tmp_path):
    return {
        "a.csv": write_csv(tmp_path / "a.csv", [
            "ORD-A1,1111.22.33333,2222.00.00001,500.00,NOK,2026-10-15,2026-10-01",
            "ORD-A2,1111.22.33333,2222.00.00002,20000.00,NOK,2026-10-15,2026-10-01",
            "ORD-DUP,3333.00.00003,2222.00.00009,100.00,NOK,2026-10-15,2026-10-01",
        ]),
        "b.csv": write_csv(tmp_path / "b.csv", [
            "ORD-B1,1111.22.33333,2222.00.00003,100.00,EUR,2026-10-15,2026-10-01",
            "ORD-B2,4444.00.00004,2222.00.00001,100.00,NOK,2027-03-01,2026-10-01",
            "ORD-BAD,4444.00.00004,2222.00.00005,-5.00,NOK,2026-10-15,2026-10-01",
        ]),
        "c.csv": write_csv(tmp_path / "c.csv", [
            "ORD-C1,4444.00.00004,2222.00.00004,100.00,NOK,2026-09-01,2026-10-01",
            "ORD-C2,1111.22.33333,2222.00.00001,100.00,NOK,2026-10-15,2026-10-01",
            "ORD-DUP,3333.00.00003,2222.00.00009,100.00,NOK,2026-10-15,2026-10-01",
        ]),
    }


def test_only_new_creditor_depends_on_import_order(tmp_path):
    files = order_files(tmp_path)
    results = {}
    for n, order in enumerate(itertools.permutations(files)):
        store = TransactionStore(tmp_path / f"order{n}.db")
        try:
            summaries = [import_path(store, files[name]) for name in order]
            stored = {s.transaction.transaction_id: set(s.flags) for s in store.all()}
        finally:
            store.close()
        results[order] = (
            stored,
            sum(len(s.duplicates) for s in summaries),
            sum(len(s.errors) for s in summaries),
        )

    failures = []
    baseline_order, (baseline, base_dups, base_errors) = next(iter(results.items()))
    for order, (stored, dups, errors) in results.items():
        if stored.keys() != baseline.keys():
            failures.append(f"{order}: stored ids {sorted(stored)} != {sorted(baseline)}")
        if (dups, errors) != (base_dups, base_errors):
            failures.append(f"{order}: duplicates/errors {(dups, errors)} != {(base_dups, base_errors)}")
        for tid in stored.keys() & baseline.keys():
            got = stored[tid] & set(NON_ORDER_FLAGS)
            want = baseline[tid] & set(NON_ORDER_FLAGS)
            if got != want:
                failures.append(f"{order} {tid}: non-history flags {sorted(got)} != {sorted(want)} in {baseline_order}")

    new_creditor_varies = {tid for tid in baseline
                           if len({"NEW_CREDITOR" in stored.get(tid, ()) for stored, _, _ in results.values()}) > 1}
    if new_creditor_varies != {"ORD-A1", "ORD-B1", "ORD-B2", "ORD-C1", "ORD-C2"}:
        failures.append(f"ids whose NEW_CREDITOR depends on order: {sorted(new_creditor_varies)}")
    always_new = {tid for tid in baseline if all("NEW_CREDITOR" in s[tid] for s, _, _ in results.values())}
    if always_new != {"ORD-A2"}:
        failures.append(f"ids flagged NEW_CREDITOR in every order: {sorted(always_new)} (expected only ORD-A2)")
    abc = results[("a.csv", "b.csv", "c.csv")][0]
    cba = results[("c.csv", "b.csv", "a.csv")][0]
    if {t for t, f in abc.items() if "NEW_CREDITOR" in f} != {"ORD-A2", "ORD-B1", "ORD-C1"}:
        failures.append(f"a,b,c NEW_CREDITOR: {sorted(t for t, f in abc.items() if 'NEW_CREDITOR' in f)}")
    if {t for t, f in cba.items() if "NEW_CREDITOR" in f} != {"ORD-A2", "ORD-B1", "ORD-B2"}:
        failures.append(f"c,b,a NEW_CREDITOR: {sorted(t for t, f in cba.items() if 'NEW_CREDITOR' in f)}")
    if (len(baseline), base_dups, base_errors) != (7, 1, 1):
        failures.append(f"stored/duplicates/errors = {(len(baseline), base_dups, base_errors)}, expected (7, 1, 1)")
    assert not failures, "\n".join(failures)


def concurrent_thread_import(tmp_path, shared_connection):
    db = tmp_path / ("shared.db" if shared_connection else "two_conns.db")
    x = big_csv(tmp_path / "x.csv", 20000, start=0)
    y = big_csv(tmp_path / "y.csv", 20000, start=10000)
    TransactionStore(db).close()
    stores = [TransactionStore(db)] * 2 if shared_connection else [TransactionStore(db), TransactionStore(db)]
    barrier = threading.Barrier(2)
    outcomes = {}

    def worker(name, store, path):
        barrier.wait()
        try:
            outcomes[name] = import_path(store, path)
        except Exception as exc:
            outcomes[name] = exc

    threads = [threading.Thread(target=worker, args=(n, s, p)) for n, s, p in zip("xy", stores, (x, y))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    for s in set(stores):
        s.close()

    failures = [f"{n}: {type(o).__name__}: {o}" for n, o in outcomes.items() if isinstance(o, Exception)]
    rows = raw_rows(db)
    failures += row_problems(rows)
    if len(rows) != 30000:
        failures.append(f"stored {len(rows)} rows, expected 30000 unique ids")
    if not failures:
        sx, sy = outcomes["x"], outcomes["y"]
        if sx.imported + sy.imported != 30000:
            failures.append(f"imported {sx.imported} + {sy.imported} != 30000")
        overlap = {f"T{i:06d}" for i in range(10000, 20000)}
        reported = sx.duplicates + sy.duplicates
        if sorted(reported) != sorted(overlap):
            failures.append(f"duplicates reported {len(reported)} (unique {len(set(reported))}), expected each of "
                            f"the 10000 shared ids exactly once")
    return failures


def test_two_threads_with_own_connections_import_into_the_same_db(tmp_path):
    failures = concurrent_thread_import(tmp_path, shared_connection=False)
    assert not failures, "\n".join(failures)


def test_two_threads_sharing_one_store_import_into_the_same_db(tmp_path):
    failures = concurrent_thread_import(tmp_path, shared_connection=True)
    assert not failures, "\n".join(failures)


def cli_failures(results):
    failures = []
    for name, (code, out, err, summary) in results.items():
        if "Traceback" in err or "locked" in err.lower():
            failures.append(f"{name}: exit {code}, stderr: {err.strip().splitlines()[-1] if err.strip() else ''}")
        elif code != 0 or summary is None:
            failures.append(f"{name}: exit {code}, stdout: {out.strip()[:200]}")
    return failures


def test_two_cli_processes_import_different_files_into_the_same_db(tmp_path):
    db = tmp_path / "procs.db"
    TransactionStore(db).close()
    x = big_csv(tmp_path / "x.csv", 20000, start=0)
    y = big_csv(tmp_path / "y.csv", 20000, start=10000)
    procs = {"x": run_cli(db, "import", str(x)), "y": run_cli(db, "import", str(y))}
    results = {n: finish(p) for n, p in procs.items()}

    failures = cli_failures(results)
    rows = raw_rows(db)
    failures += row_problems(rows)
    if len(rows) != 30000:
        failures.append(f"stored {len(rows)} rows, expected 30000 unique ids")
    if not failures:
        imported = sum(r[3][0] for r in results.values())
        dups = sum(r[3][2] for r in results.values())
        if (imported, dups) != (30000, 10000):
            failures.append(f"summed Imported/Duplicates = {(imported, dups)}, expected (30000, 10000)")
    assert not failures, "\n".join(failures)


def test_two_cli_processes_import_the_same_file_at_once(tmp_path):
    db = tmp_path / "same.db"
    TransactionStore(db).close()
    f = big_csv(tmp_path / "same.csv", 20000)
    procs = {"first": run_cli(db, "import", str(f)), "second": run_cli(db, "import", str(f))}
    results = {n: finish(p) for n, p in procs.items()}

    failures = cli_failures(results)
    rows = raw_rows(db)
    failures += row_problems(rows)
    if len(rows) != 20000:
        failures.append(f"stored {len(rows)} rows, expected 20000")
    if not failures:
        imported = sum(r[3][0] for r in results.values())
        dups = sum(r[3][2] for r in results.values())
        if (imported, dups) != (20000, 20000):
            failures.append(f"summed Imported/Duplicates = {(imported, dups)}, expected (20000, 20000)")
    assert not failures, "\n".join(failures)


def test_crash_mid_file_leaves_consistent_rows_and_reimport_completes(tmp_path):
    path = write_csv(tmp_path / "crash.csv", [
        f"CR-{i},1111.00.0000{i % 3},2222.00.0000{i},{i * 4000}.00,NOK,2026-11-01,2026-10-20" for i in range(1, 9)
    ])
    calls = []

    def crash_on_fifth(tx, history, import_date):
        calls.append(tx.transaction_id)
        if len(calls) == 5:
            raise RuntimeError("simulated crash")
        return rules.evaluate(tx, history, import_date)

    db = tmp_path / "crash.db"
    store = TransactionStore(db)
    crashed = False
    try:
        import_path(store, path, crash_on_fifth)
    except RuntimeError:
        crashed = True
    finally:
        store.close()

    failures = [] if crashed else ["evaluate raised but import_transactions did not propagate it"]
    after_crash = raw_rows(db)
    failures += row_problems(after_crash)
    partial = sorted(r[0] for r in after_crash)
    if partial:
        failures.append(f"after crash on row 5 stored {partial}; an import is one transaction, expected nothing kept")

    store = TransactionStore(db)
    try:
        summary = import_path(store, path)
        resumed = {s.transaction.transaction_id: s.flags for s in store.all()}
    finally:
        store.close()
    failures += row_problems(raw_rows(db))
    if (summary.imported, len(summary.duplicates), len(resumed)) != (8, 0, 8):
        failures.append(f"re-import: imported {summary.imported}, duplicates {len(summary.duplicates)}, "
                        f"stored {len(resumed)}, expected 8/0/8")

    clean = TransactionStore(tmp_path / "clean.db")
    try:
        import_path(clean, path)
        uninterrupted = {s.transaction.transaction_id: s.flags for s in clean.all()}
    finally:
        clean.close()
    if resumed != uninterrupted:
        failures.append(f"flags after crash+re-import {resumed} != uninterrupted import {uninterrupted}")
    assert not failures, "\n".join(failures)


def test_killed_cli_import_leaves_consistent_db_and_reimport_completes(tmp_path):
    db = tmp_path / "killed.db"
    TransactionStore(db).close()
    path = big_csv(tmp_path / "big.csv", TOTAL_BIG)
    journal = Path(f"{db}-journal")
    proc = run_cli(db, "import", str(path))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and proc.poll() is None and not journal.exists():
        time.sleep(0.005)
    finished_before_kill = proc.poll() is not None
    proc.kill()
    proc.communicate(timeout=30)

    failures = []
    conn = sqlite3.connect(str(db))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if integrity != "ok":
        failures.append(f"integrity_check after kill: {integrity}")
    after_kill = raw_rows(db)
    failures += row_problems(after_kill)
    if finished_before_kill:
        failures.append(f"import finished before it could be killed ({len(after_kill)} rows); file too small")
    elif after_kill:
        failures.append(f"after kill mid-import {len(after_kill)} rows kept; an import is one transaction, expected 0")

    code, out, err, summary = finish(run_cli(db, "import", str(path)))
    rows = raw_rows(db)
    failures += row_problems(rows)
    if code != 0 or "Traceback" in err:
        failures.append(f"re-import exit {code}: {err.strip()[-300:]}")
    if len(rows) != TOTAL_BIG:
        failures.append(f"after re-import {len(rows)} rows stored, expected {TOTAL_BIG}")
    if summary and (summary[0] + summary[2], summary[2]) != (TOTAL_BIG, len(after_kill)):
        failures.append(f"re-import summary {summary}: duplicates should equal the {len(after_kill)} rows kept")
    assert not failures, "\n".join(failures)


def index_names(db):
    conn = sqlite3.connect(str(db))
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    finally:
        conn.close()


def test_current_schema_database_reopens_and_keeps_working(tmp_path):
    db = tmp_path / "current.db"
    first = write_csv(tmp_path / "first.csv", ["OLD-1,1111.00.00001,2222.00.00001,100.00,NOK,2026-11-01,2026-10-20"])
    second = write_csv(tmp_path / "second.csv", [
        "OLD-1,1111.00.00001,2222.00.00001,100.00,NOK,2026-11-01,2026-10-20",
        "OLD-2,1111.00.00001,2222.00.00002,100.00,NOK,2026-11-01,2026-10-20",
    ])
    store = TransactionStore(db)
    import_path(store, first)
    before = store.all()
    store.close()

    store = TransactionStore(db)
    try:
        failures = [] if store.all() == before else ["rows changed after reopen"]
        summary = import_path(store, second)
        flags = {s.transaction.transaction_id: s.flags for s in store.all()}
    finally:
        store.close()
    if summary.duplicates != ["OLD-1"] or flags.get("OLD-2") != ("NEW_CREDITOR",):
        failures.append(f"after reopen: duplicates {summary.duplicates}, OLD-2 flags {flags.get('OLD-2')}")
    if "ix_debtor_creditor" not in index_names(db):
        failures.append("index missing after reopen")
    assert not failures, "\n".join(failures)


def test_older_database_without_index_opens_and_gets_the_index(tmp_path):
    db = tmp_path / "older.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE transactions (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT NOT NULL UNIQUE,
            debtor_account TEXT NOT NULL,
            creditor_account TEXT NOT NULL,
            amount TEXT NOT NULL,
            currency TEXT NOT NULL,
            due_date TEXT NOT NULL,
            created_date TEXT,
            import_date TEXT NOT NULL,
            flags TEXT NOT NULL
        );
        INSERT INTO transactions (transaction_id, debtor_account, creditor_account, amount, currency,
                                  due_date, created_date, import_date, flags)
        VALUES ('LEGACY-1', '11110000001', '22220000001', '100.00', 'NOK', '2026-11-01', '2026-10-01',
                '2026-10-01', '[]');
    """)
    conn.close()
    path = write_csv(tmp_path / "new.csv", [
        "LEGACY-1,1111.00.00001,2222.00.00001,100.00,NOK,2026-11-01,2026-10-20",
        "LEGACY-2,1111.00.00001,2222.00.00009,100.00,NOK,2026-11-01,2026-10-20",
    ])
    store = TransactionStore(db)
    try:
        summary = import_path(store, path)
        flags = {s.transaction.transaction_id: s.flags for s in store.all()}
    finally:
        store.close()
    failures = []
    if "ix_debtor_creditor" not in index_names(db):
        failures.append("opening an older DB did not add ix_debtor_creditor")
    if summary.duplicates != ["LEGACY-1"]:
        failures.append(f"legacy row not seen as duplicate: {summary.duplicates}")
    if flags.get("LEGACY-2") != ("NEW_CREDITOR",):
        failures.append(f"legacy row not used as history: LEGACY-2 flags {flags.get('LEGACY-2')}")
    assert not failures, "\n".join(failures)


def test_corrupt_db_file_gives_a_clear_error_not_a_traceback(tmp_path):
    db = tmp_path / "corrupt.db"
    db.write_bytes(b"this is not a sqlite database\x00" * 200)
    path = write_csv(tmp_path / "one.csv", ["COR-1,1111.00.00001,2222.00.00001,100.00,NOK,2026-11-01,2026-10-20"])
    code, out, err, _ = finish(run_cli(db, "import", str(path)))
    failures = []
    if code == 0:
        failures.append("exit code 0 for a corrupt --db file")
    if "Traceback" in err:
        failures.append(f"traceback instead of a clear error, last line: {err.strip().splitlines()[-1]}")
    elif "database" not in (out + err).lower():
        failures.append(f"error does not mention the database: {(out + err).strip()[:200]}")
    assert not failures, "\n".join(failures)


PAIN001 = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr><MsgId>MSG-1</MsgId><CreDtTm>2026-10-20T10:00:00</CreDtTm><NbOfTxs>2</NbOfTxs></GrpHdr>
    <PmtInf>
      <PmtInfId>PMT-1</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <ReqdExctnDt>2026-11-01</ReqdExctnDt>
      <Dbtr><Nm>Debtor</Nm></Dbtr>
      <DbtrAcct><Id><Othr><Id>12345678903</Id></Othr></Id></DbtrAcct>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>XF-KNOWN</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="NOK">100.00</InstdAmt></Amt>
        <CdtrAcct><Id><Othr><Id>98765432109</Id></Othr></Id></CdtrAcct>
      </CdtTrfTxInf>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>XF-NEW</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="NOK">100.00</InstdAmt></Amt>
        <CdtrAcct><Id><IBAN>NO9386011117947</IBAN></Id></CdtrAcct>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>
"""


def test_history_from_csv_applies_to_a_later_pain001_import(tmp_path):
    csv_path = write_csv(tmp_path / "first.csv", ["XF-CSV,1234.56.78903,9876.54.32109,100.00,NOK,2026-11-01,2026-10-20"])
    xml_path = tmp_path / "second.xml"
    xml_path.write_text(PAIN001, encoding="utf-8")
    store = TransactionStore(tmp_path / "xformat.db")
    try:
        first = import_path(store, csv_path)
        second = import_path(store, xml_path)
        flags = {s.transaction.transaction_id: s.flags for s in store.all()}
    finally:
        store.close()
    failures = []
    if (first.imported, second.imported, second.errors) != (1, 2, []):
        failures.append(f"imports: csv {first.imported}, xml {second.imported}, xml errors {second.errors}")
    if flags.get("XF-CSV") != ():
        failures.append(f"XF-CSV (debtor's first payment): {flags.get('XF-CSV')}")
    if flags.get("XF-KNOWN") != ():
        failures.append(f"XF-KNOWN (same creditor, dots in CSV, none in XML): expected no flags, got {flags.get('XF-KNOWN')}")
    if flags.get("XF-NEW") != ("NEW_CREDITOR",):
        failures.append(f"XF-NEW (known debtor, new IBAN creditor): expected NEW_CREDITOR, got {flags.get('XF-NEW')}")
    assert not failures, "\n".join(failures)
