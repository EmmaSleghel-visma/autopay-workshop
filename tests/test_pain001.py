import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from fraud_detection import rules
from fraud_detection.pain001 import Pain001Importer
from fraud_detection.service import import_transactions, importer_for
from fraud_detection.importer import CsvImporter
from fraud_detection.storage import TransactionStore

SAMPLE_V03 = Path(__file__).parent.parent / "samples" / "pain001_v03.xml"
NS09 = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"


def doc(ns, pmt_infs, cre_dt_tm="2026-10-23T10:00:00"):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><Document xmlns="{ns}"><CstmrCdtTrfInitn>'
        f"<GrpHdr><MsgId>M1</MsgId><CreDtTm>{cre_dt_tm}</CreDtTm></GrpHdr>{pmt_infs}"
        "</CstmrCdtTrfInitn></Document>"
    )


def pmt_inf(txs, reqd="<ReqdExctnDt><Dt>2026-11-15</Dt></ReqdExctnDt>", debtor="<IBAN>NO9386011117947</IBAN>"):
    return f"<PmtInf><PmtInfId>P1</PmtInfId>{reqd}<DbtrAcct><Id>{debtor}</Id></DbtrAcct>{txs}</PmtInf>"


def tx(e2e="E1", instr="", amount='<InstdAmt Ccy="NOK">100.00</InstdAmt>',
       cdtr="<CdtrAcct><Id><Othr><Id>1234.56.78903</Id></Othr></Id></CdtrAcct>"):
    instr_el = f"<InstrId>{instr}</InstrId>" if instr else ""
    return f"<CdtTrfTxInf><PmtId>{instr_el}<EndToEndId>{e2e}</EndToEndId></PmtId><Amt>{amount}</Amt>{cdtr}</CdtTrfTxInf>"


def parse(text):
    return Pain001Importer().parse(io.StringIO(text))


def test_customer_v03_sample_maps_fields():
    with open(SAMPLE_V03, encoding="utf-8") as f:
        result = Pain001Importer().parse(f)
    assert result.errors == []
    assert [t.transaction_id for t in result.transactions] == ["E2E-0001", "E2E-0002", "E2E-0003", "E2E-0004"]
    first, _, eur, last = result.transactions
    assert first.debtor_account == "12345678903"
    assert first.creditor_account == "98765432109"
    assert first.amount == Decimal("2500.00") and first.currency == "NOK"
    assert first.due_date == date(2026, 11, 15)
    assert first.created_date == date(2026, 10, 23)
    assert eur.currency == "EUR" and eur.creditor_account == "DE00000000000000000000"
    assert last.due_date == date(2027, 3, 1)  # second PmtInf block has its own date


def test_customer_v03_sample_gives_qa_expected_flags(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    with open(SAMPLE_V03, encoding="utf-8") as f:
        summary = import_transactions(f, Pain001Importer(), store, rules.evaluate, date(2026, 10, 23))
    assert (summary.imported, summary.flagged, summary.duplicates, summary.errors) == (4, 3, [], [])
    flags = {s.transaction.transaction_id: set(s.flags) for s in store.all()}
    assert flags == {
        "E2E-0001": set(),
        "E2E-0002": {"HIGH_AMOUNT", "NEW_CREDITOR"},
        "E2E-0003": {"NEW_CREDITOR", "UNSUPPORTED_CURRENCY"},
        "E2E-0004": {"FAR_FUTURE_DUE"},
    }


def test_v09_date_and_datetime_choice():
    result = parse(doc(NS09,
        pmt_inf(tx("A")) +
        pmt_inf(tx("B"), reqd="<ReqdExctnDt><DtTm>2026-12-01T08:00:00</DtTm></ReqdExctnDt>")))
    assert result.errors == []
    assert [t.due_date for t in result.transactions] == [date(2026, 11, 15), date(2026, 12, 1)]


def test_notprovided_end_to_end_id_falls_back_to_instr_id():
    result = parse(doc(NS09, pmt_inf(tx("NOTPROVIDED", instr="INS-9") + tx("NOTPROVIDED"))))
    assert [t.transaction_id for t in result.transactions] == ["INS-9"]
    assert "NOTPROVIDED" in result.errors[0].message


def test_row_level_problems_are_errors_and_other_rows_still_import():
    result = parse(doc(NS09, pmt_inf(
        tx("OK") +
        tx("NO-CDTR", cdtr="") +
        tx("EQVT", amount='<EqvtAmt><Amt Ccy="EUR">5</Amt><CcyOfTrf>NOK</CcyOfTrf></EqvtAmt>') +
        tx("ZERO", amount='<InstdAmt Ccy="NOK">0</InstdAmt>'))))
    assert [t.transaction_id for t in result.transactions] == ["OK"]
    messages = " | ".join(e.message for e in result.errors)
    assert "NO-CDTR" in messages and "CdtrAcct" in messages
    assert "EQVT" in messages and "EqvtAmt" in messages
    assert "ZERO" in messages and "greater than zero" in messages


def test_wrong_document_type_and_broken_xml_are_rejected():
    assert "unsupported document type" in parse(doc("urn:iso:std:iso:20022:tech:xsd:pain.008.001.02", "")).errors[0].message
    assert "not valid XML" in parse("<Document><unclosed>").errors[0].message


def test_entity_expansion_bomb_is_refused():
    bomb = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">'
            + "".join(f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(9))
            + f']><Document xmlns="{NS09}">&j;</Document>')
    result = parse(bomb)
    assert result.transactions == []
    assert "DOCTYPE" in result.errors[0].message


def test_history_matches_across_csv_and_xml(tmp_path):
    store = TransactionStore(tmp_path / "fraud.db")
    csv = ("transaction_id,debtor_account,creditor_account,amount,currency,due_date\n"
           "C1,NO93 8601 1117 947,1234 56 78903,100.00,NOK,2026-11-15\n")
    import_transactions(io.StringIO(csv), CsvImporter(), store, rules.evaluate, date(2026, 10, 23))
    xml = doc(NS09, pmt_inf(tx("X1") + tx("X2", cdtr="<CdtrAcct><Id><IBAN>NO0000000000000</IBAN></Id></CdtrAcct>")))
    import_transactions(io.StringIO(xml), Pain001Importer(), store, rules.evaluate, date(2026, 10, 23))
    flags = {s.transaction.transaction_id: s.flags for s in store.all()}
    assert flags["X1"] == ()  # same debtor and creditor as C1 once normalised
    assert flags["X2"] == ("NEW_CREDITOR",)


def test_importer_for_picks_by_extension():
    assert isinstance(importer_for("customer.XML"), Pain001Importer)
    assert isinstance(importer_for("transactions.csv"), CsvImporter)


def test_internal_dtd_entity_is_refused():
    text = doc(NS09, pmt_inf(tx("&e2e;"))).replace(
        "<Document", '<!DOCTYPE Document [<!ENTITY e2e "DTD-E2E-01">]><Document', 1)
    result = parse(text)
    assert result.transactions == []
    assert "DOCTYPE" in result.errors[0].message
