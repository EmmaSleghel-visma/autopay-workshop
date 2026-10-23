"""Robustness: the same Norwegian CSV and a Latin-1 pain.001 in common encodings, imported through the CLI."""

from fraud_detection.__main__ import main
from fraud_detection.storage import TransactionStore

IDS = ["T-ÆØÅ-1", "T-æøå-2"]
CSV_TEXT = (
    "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date\r\n"
    f"{IDS[0]},1234.56.78903,9876.54.32109,500.00,NOK,2026-11-15,2026-10-20\r\n"
    f"{IDS[1]},1234 56 78903,9876 54 32109,750.00,NOK,2026-11-20,2026-10-21\r\n"
)

PAIN001_LATIN1 = """<?xml version="1.0" encoding="ISO-8859-1"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>ENC-0001</MsgId>
      <CreDtTm>2026-10-23T10:00:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
      <CtrlSum>500.00</CtrlSum>
      <InitgPty><Nm>Blåbær og Rødgrøt AS</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>ENC-PMT-ÆØÅ</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs>
      <ReqdExctnDt>2026-11-15</ReqdExctnDt>
      <Dbtr><Nm>Ærlig Øl Ålesund AS</Nm></Dbtr>
      <DbtrAcct><Id><Othr><Id>12345678903</Id></Othr></Id></DbtrAcct>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E-ÆØÅ-1</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="NOK">500.00</InstdAmt></Amt>
        <Cdtr><Nm>Søren Bjørnstad Æsthetikk</Nm></Cdtr>
        <CdtrAcct><Id><Othr><Id>98765432109</Id></Othr></Id></CdtrAcct>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>
"""


def run_cli(tmp_path, capsys, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    db = tmp_path / f"{name}.db"
    try:
        code = main(["--db", str(db), "import", str(path)])
    except Exception as exc:
        return None, f"CLI crashed with {type(exc).__name__}: {exc}", []
    out = capsys.readouterr().out
    store = TransactionStore(db)
    try:
        ids = [s.transaction.transaction_id for s in store.all()]
    finally:
        store.close()
    return code, out, ids


def check(tmp_path, capsys, label, name, data, expected_ids):
    code, out, ids = run_cli(tmp_path, capsys, name, data)
    if code is None:
        return [f"{label}: {out}"]
    if code == 0:
        if ids != expected_ids:
            return [f"{label}: exit 0 but stored ids {ids!r}, expected {expected_ids!r}"]
        return []
    if code == 1:
        failures = []
        if ids:
            failures.append(f"{label}: rejected (exit 1) but {len(ids)} row(s) stored: {ids!r}")
        if not out.strip() or "Traceback" in out:
            failures.append(f"{label}: rejected (exit 1) without a readable message: {out!r}")
        return failures
    return [f"{label}: unexpected exit code {code!r}"]


def assert_csv(tmp_path, capsys, label, data):
    failures = check(tmp_path, capsys, label, "nordic.csv", data, IDS)
    assert not failures, "\n".join(failures)


def test_utf8_csv(tmp_path, capsys):
    assert_csv(tmp_path, capsys, "UTF-8", CSV_TEXT.encode("utf-8"))


def test_utf8_with_bom_csv(tmp_path, capsys):
    assert_csv(tmp_path, capsys, "UTF-8 with BOM", CSV_TEXT.encode("utf-8-sig"))


def test_windows_1252_csv(tmp_path, capsys):
    assert_csv(tmp_path, capsys, "Windows-1252", CSV_TEXT.encode("cp1252"))


def test_utf16_le_with_bom_csv(tmp_path, capsys):
    assert_csv(tmp_path, capsys, "UTF-16 LE with BOM", b"\xff\xfe" + CSV_TEXT.encode("utf-16-le"))


def test_latin1_csv(tmp_path, capsys):
    assert_csv(tmp_path, capsys, "Latin-1", CSV_TEXT.encode("latin-1"))


def test_pain001_declared_iso_8859_1(tmp_path, capsys):
    data = PAIN001_LATIN1.encode("latin-1")
    failures = check(tmp_path, capsys, "pain.001 ISO-8859-1", "latin1_pain001.xml", data, ["E2E-ÆØÅ-1"])
    assert not failures, "\n".join(failures)


def test_pain001_with_a_wrong_or_unknown_declared_encoding(tmp_path, capsys):
    failures = []
    for declared in ("TF-8", "x-unknown-charset", "UTF-16"):
        text = PAIN001_LATIN1.replace('encoding="ISO-8859-1"', f'encoding="{declared}"')
        failures += check(tmp_path, capsys, f"pain.001 UTF-8 bytes declared {declared}",
                          f"declared_{declared}.xml", text.encode("utf-8"), ["E2E-ÆØÅ-1"])
    assert not failures, "\n".join(failures)
