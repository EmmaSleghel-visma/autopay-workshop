"""Single source of truth for the pain.001 XML import test data.

Running this file writes:
  data/pain001/p*.xml              transaction files, imported in IMPORT_ORDER into one store
  data/pain001/f*.xml              whole-file negative and corner cases (same store, same run)
  data/pain001/x_cross_csv.xml     imported after data/all_rules.csv (CSV and XML share history)
  data/pain001/expected_pain001.json

Every case has a category:
  POS     valid, everyday input; the app does what it should
  NEG     invalid or hostile input, or input that must NOT trigger a rule
  CORNER  boundaries and unusual-but-valid input

Mapping under test: transaction_id = EndToEndId (InstrId when NOTPROVIDED), debtor = PmtInf/DbtrAcct,
creditor = CdtTrfTxInf/CdtrAcct, amount = InstdAmt + @Ccy, due = PmtInf/ReqdExctnDt,
created = GrpHdr/CreDtTm. Import date 2026-10-23. Stdlib only.

Judgement calls:
  - a prefixed namespace (ns0:Document) is the same XML document as a default namespace one: accepted.
  - a DOCTYPE (internal or external entity) is refused as a whole file: pain.001 never needs one.
  - IBAN and BBAN of the same account are different keys (PO rule only strips spaces and dots).
  - a non-UTF-8 / binary upload must be reported as an error, not crash the import.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "data" / "pain001"
IMPORT_DATE = "2026-10-23"

NS = {
    "03": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03",
    "09": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09",
    "12": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.12",
    "008": "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02",
}
R1, R2, R3 = "HIGH_AMOUNT", "NEW_CREDITOR", "FAR_FUTURE_DUE"
CUR, PAST = "UNSUPPORTED_CURRENCY", "PAST_DUE_DATE"
POS, NEG, CORNER = "POS", "NEG", "CORNER"
DUP, ERR = "DUPLICATE", "ERROR"

C_A = "9000.11.00001"
C_B = "9000.11.00002"
C_C = "9000.11.00003"
C_D = "9000.11.00004"
CRE = "2026-10-01T09:00:00"


def norm(account):
    return account.replace(" ", "").replace(".", "").strip()


def account_xml(account):
    if account[:2].isalpha():
        return f"<IBAN>{account}</IBAN>"
    return f"<Othr><Id>{account}</Id><SchmeNm><Cd>BBAN</Cd></SchmeNm></Othr>"


def t(case, cat, e2e, creditor, amount, expect, note, ccy="NOK", instr="", amt_xml=None, tid=None, error=None):
    """One CdtTrfTxInf; expect is a flag list, DUPLICATE or ERROR; error lists substrings the error message must name."""
    pmt_id = (f"<InstrId>{instr}</InstrId>" if instr else "") + f"<EndToEndId>{e2e}</EndToEndId>"
    amt = amt_xml or f'<InstdAmt Ccy="{ccy}">{amount}</InstdAmt>'
    cdtr = "" if creditor is None else f"<CdtrAcct><Id>{account_xml(creditor)}</Id></CdtrAcct>"
    xml = (f"<CdtTrfTxInf><PmtId>{pmt_id}</PmtId><Amt>{amt}</Amt>"
           f"<Cdtr><Nm>Creditor {case}</Nm></Cdtr>{cdtr}<RmtInf><Ustrd>{case}</Ustrd></RmtInf></CdtTrfTxInf>")
    if tid is None:
        tid = instr if e2e == "NOTPROVIDED" else e2e
    status = expect if isinstance(expect, str) else "IMPORTED"
    entry = {"case": case, "category": cat, "transaction_id": tid, "status": status,
             "flags": sorted(expect) if isinstance(expect, list) else [], "note": note}
    if status == ERR:
        entry["error_contains"] = error or [tid]
    meta = {"creditor": norm(creditor) if creditor else None, "amount": amount.strip() if amount else None, "currency": ccy.strip().upper()}
    return {"xml": xml, "entry": entry, "meta": meta}


def pmt(pid, debtor, due, txs, due_kind="Dt"):
    """One PmtInf; due_kind is Dt or DtTm and only matters for .09."""
    return {"pid": pid, "debtor": debtor, "due": due, "due_kind": due_kind, "txs": txs}


def document(version, cre, pmts, ns_prefix="", doctype=""):
    ns = NS[version]
    p = f"{ns_prefix}:" if ns_prefix else ""
    bic = "BIC" if version == "03" else "BICFI"
    blocks = []
    for b in pmts:
        if version == "09":
            reqd = f"<ReqdExctnDt><{b['due_kind']}>{b['due']}</{b['due_kind']}></ReqdExctnDt>"
        else:
            reqd = f"<ReqdExctnDt>{b['due']}</ReqdExctnDt>"
        txs = "".join(x["xml"] for x in b["txs"])
        blocks.append(f"<PmtInf><PmtInfId>{b['pid']}</PmtInfId><PmtMtd>TRF</PmtMtd><NbOfTxs>{len(b['txs'])}</NbOfTxs>{reqd}"
                      f"<Dbtr><Nm>Debtor {b['pid']}</Nm></Dbtr><DbtrAcct><Id>{account_xml(b['debtor'])}</Id></DbtrAcct>"
                      f"<DbtrAgt><FinInstnId><{bic}>TESTNOKKXXX</{bic}></FinInstnId></DbtrAgt>{txs}</PmtInf>")
    n = sum(len(b["txs"]) for b in pmts)
    body = (f"<CstmrCdtTrfInitn><GrpHdr><MsgId>QA-{cre}</MsgId><CreDtTm>{cre}</CreDtTm><NbOfTxs>{n}</NbOfTxs>"
            f"<InitgPty><Nm>QA</Nm></InitgPty></GrpHdr>{''.join(blocks)}</CstmrCdtTrfInitn>")
    if p:
        body = _prefix(body, p)
    root = f'<{p}Document xmlns{":" + ns_prefix if ns_prefix else ""}="{ns}">{body}</{p}Document>'
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{doctype}{root}\n'


def _prefix(xml, p):
    return re.sub(r"<(/?)([A-Za-z]+)", lambda m: f"<{m.group(1)}{p}{m.group(2)}", xml)


def tx_entries(cre, pmts):
    out = []
    for b in pmts:
        for x in b["txs"]:
            e = dict(x["entry"])
            if e["status"] == "IMPORTED":
                e["fields"] = {"debtor_account": norm(b["debtor"]), "creditor_account": x["meta"]["creditor"],
                               "amount": x["meta"]["amount"], "currency": x["meta"]["currency"],
                               "due_date": b["due"][:10], "created_date": cre[:10]}
            out.append(e)
    return out


D01, D02, D03, D04 = "86011117941", "NO9386011117942", "8601.11.17943", "8601.11.17944"
D05, D06, D07, D08 = "8601.11.17945", "8601.11.17946", "8601.11.17947", "8601.11.17948"
D09, D10, D11, D12 = "8601.11.17949", "8601.11.17950", "8601.11.17951", "8601.11.17952"

P01 = ("03", CRE, [
    pmt("P01-A", D01, "2026-10-15", [
        t("V03-01", POS, "V03-E2E-01", C_A, "1500.00", [], "debtor's first txn: clean"),
        t("V03-02", POS, "V03-E2E-02", C_A, "2300.50", [], "known creditor, normal amount: clean"),
        t("V03-03", POS, "V03-E2E-03", C_A, "75000.00", [R1], "large amount"),
        t("V03-04", POS, "V03-E2E-04", C_B, "800.00", [R2], "known debtor pays a new creditor"),
    ]),
    pmt("P01-B", D01, "2027-04-01", [
        t("V03-05", POS, "V03-E2E-05", C_A, "800.00", [R3], "second PmtInf has its own due date, 6 months out"),
    ]),
])

P02 = ("09", CRE, [
    pmt("P02-A", D02, "2026-10-20", [
        t("V09-01", POS, "V09-E2E-01", C_A, "1200.00", [], "IBAN debtor, first txn: clean"),
        t("V09-02", POS, "V09-E2E-02", C_A, "1300.00", [], "same debtor, due date and creditor: clean"),
        t("V09-03", POS, "V09-E2E-03", C_B, "1400.00", [R2], "several txns per PmtInf share the debtor: B is new"),
    ]),
    pmt("P02-B", D03, "2026-11-01T10:00:00", [
        t("V09-04", POS, "V09-E2E-04", C_B, "500.00", [], "other debtor in another PmtInf: first txn, clean"),
        t("V09-05", POS, "V09-E2E-05", C_C, "600.00", [R2], "second debtor pays a new creditor"),
    ], due_kind="DtTm"),
])

P03 = ("09", CRE, [
    pmt("P03-A", D04, "2026-10-15", [
        t("R1-01", CORNER, "R1-E2E-01", C_A, "10000.00", [], "exactly 10,000.00 is not flagged"),
        t("R1-02", CORNER, "R1-E2E-02", C_A, "10000.01", [R1], "one ore over the limit"),
        t("R1-03", CORNER, "R1-E2E-03", C_A, "9999.99", [], "one ore under"),
        t("R1-04", CORNER, "R1-E2E-04", C_A, "10000", [], "no decimals, equal to limit"),
        t("R1-05", CORNER, "R1-E2E-05", C_A, "10000.001", [R1], "three decimals, just over the limit (schema allows 5)"),
        t("R1-06", CORNER, "R1-E2E-06", C_A, "0.01", [], "smallest amount"),
        t("R1-07", NEG, "R1-E2E-07", C_A, "5000.00", [], "ordinary amount must not trip R1"),
    ]),
])

P04 = ("03", CRE, [
    pmt("P04-A", D05, "2027-01-01", [t("R3-01", CORNER, "R3-E2E-01", C_A, "100.00", [], ".03: exactly CreDtTm + 3 months is not flagged")]),
    pmt("P04-B", D05, "2027-01-02", [t("R3-02", CORNER, "R3-E2E-02", C_A, "100.00", [R3], ".03: 3 months + 1 day")]),
    pmt("P04-C", D05, "2026-10-01", [t("R3-03", CORNER, "R3-E2E-03", C_A, "100.00", [], "due date equals CreDtTm date")]),
    pmt("P04-D", D05, "2026-12-01", [t("R3-04", NEG, "R3-E2E-04", C_A, "100.00", [], "2 months out must not trip R3")]),
])

P05 = ("09", "2026-01-31T08:00:00", [
    pmt("P05-A", D06, "2026-04-30", [t("R3-05", CORNER, "R3-E2E-05", C_A, "100.00", [], ".09 Dt month end: Jan 31 + 3m = Apr 30")]),
    pmt("P05-B", D06, "2026-05-01", [t("R3-06", CORNER, "R3-E2E-06", C_A, "100.00", [R3], ".09 Dt month end + 1 day")]),
    pmt("P05-C", D06, "2026-04-30T23:59:59", [t("R3-07", CORNER, "R3-E2E-07", C_A, "100.00", [], ".09 DtTm month end, late in the day")], due_kind="DtTm"),
    pmt("P05-D", D06, "2026-05-01T00:00:00", [t("R3-08", CORNER, "R3-E2E-08", C_A, "100.00", [R3], ".09 DtTm month end + 1 day at midnight")], due_kind="DtTm"),
])

P06 = ("09", CRE, [
    pmt("P06-A", D07, "2027-01-01", [t("R3-09", CORNER, "R3-E2E-09", C_A, "100.00", [], ".09 Dt exactly 3 months")]),
    pmt("P06-B", D07, "2027-01-02", [t("R3-10", CORNER, "R3-E2E-10", C_A, "100.00", [R3], ".09 Dt 3 months + 1 day")]),
    pmt("P06-C", D07, "2027-01-01T23:59:59", [t("R3-11", CORNER, "R3-E2E-11", C_A, "100.00", [], ".09 DtTm exactly 3 months (time ignored)")], due_kind="DtTm"),
    pmt("P06-D", D07, "2027-01-02T00:00:00", [t("R3-12", CORNER, "R3-E2E-12", C_A, "100.00", [R3], ".09 DtTm 3 months + 1 day")], due_kind="DtTm"),
    pmt("P06-E", D07, "2027-06-01", [t("R3-13", POS, "R3-E2E-13", C_A, "100.00", [R3], "clearly far in the future")]),
])

P07 = ("03", CRE, [
    pmt("P07-A", D08, "2026-09-30", [t("PAST-01", CORNER, "PAST-E2E-01", C_A, "100.00", [PAST], ".03: due one day before CreDtTm: PAST_DUE_DATE, kept (PO)")]),
    pmt("P07-B", D08, "2026-09-01", [t("PAST-02", NEG, "PAST-E2E-02", C_A, "100.00", [PAST], ".03: due a month before CreDtTm: PAST_DUE_DATE, kept (PO)")]),
])

P08 = ("09", CRE, [
    pmt("P08-A", D09, "2026-09-30", [t("PAST-03", CORNER, "PAST-E2E-03", C_A, "100.00", [PAST], ".09 Dt one day before CreDtTm")]),
    pmt("P08-B", D09, "2026-09-30T23:59:59", [t("PAST-04", CORNER, "PAST-E2E-04", C_A, "100.00", [PAST], ".09 DtTm one day before CreDtTm")], due_kind="DtTm"),
])

P09 = ("09", CRE, [
    pmt("P09-A", D10, "2026-10-15", [
        t("CUR-01", NEG, "CUR-E2E-01", C_A, "100.00", [], "EUR under the EUR limit, debtor's first txn: no flags", ccy="EUR"),
        t("CUR-02", POS, "CUR-E2E-02", C_A, "50000.00", [R1], "SEK over the SEK limit: HIGH_AMOUNT only", ccy="SEK"),
        t("CUR-03", NEG, "CUR-E2E-03", C_A, "100.00", [], "NOK control: no currency flag"),
        t("CUR-05", CORNER, "CUR-E2E-05", C_A, "10000.00", [], "SEK exactly at the limit is not flagged", ccy="SEK"),
        t("CUR-06", CORNER, "CUR-E2E-06", C_A, "10000.01", [R1], "SEK one ore over the limit", ccy="SEK"),
        t("CUR-07", CORNER, "CUR-E2E-07", C_A, "1000.00", [], "EUR exactly at the EUR limit is not flagged", ccy="EUR"),
        t("CUR-08", CORNER, "CUR-E2E-08", C_A, "1000.01", [R1], "EUR one cent over the EUR limit", ccy="EUR"),
        t("CUR-09", CORNER, "CUR-E2E-09", C_A, "999.99", [], "EUR one cent under the EUR limit", ccy="EUR"),
        t("CUR-10", CORNER, "CUR-E2E-10", C_A, "1000.001", [R1], "EUR three decimals, just over the EUR limit", ccy="EUR"),
        t("CUR-11", POS, "CUR-E2E-11", C_A, "1500.00", [R1], "EUR 1500 is high, the same amount in NOK is not (no conversion)", ccy="EUR"),
        t("CUR-12", NEG, "CUR-E2E-12", C_A, "1500.00", [], "NOK 1500 control for CUR-11: no flags"),
        t("CUR-13", CORNER, "CUR-E2E-13", C_A, "50000.00", [R1], "Ccy=\"sek\" upper-cased on import: SEK limit applies", ccy="sek"),
        t("CUR-14", NEG, "CUR-E2E-14", C_A, "50000.00", [CUR], "USD over every limit: UNSUPPORTED_CURRENCY only, no HIGH_AMOUNT", ccy="USD"),
        t("CUR-15", NEG, "CUR-E2E-15", C_A, "50000.00", [CUR], "DKK (Nordic neighbour): unsupported, no HIGH_AMOUNT", ccy="DKK"),
        t("CUR-16", NEG, "CUR-E2E-16", C_A, "100.00", [CUR], "GBP: unsupported", ccy="GBP"),
        t("CUR-17", NEG, "CUR-E2E-17", C_A, "5000.00", [CUR], "Ccy=\"EURO\" is not EUR: imported as unsupported, no HIGH_AMOUNT", ccy="EURO"),
    ]),
    pmt("P09-B", D10, "2027-06-01", [
        t("CUR-04", POS, "CUR-E2E-04", C_B, "20000.00", [R1, R2, R3], "EUR high + new creditor + far due: no currency flag", ccy="EUR"),
        t("CUR-18", NEG, "CUR-E2E-18", C_C, "50000.00", [CUR, R2, R3], "USD + new creditor + far due: other rules still apply, no HIGH_AMOUNT", ccy="USD"),
    ]),
])

P10 = ("03", CRE, [
    pmt("P10-A", "1234.56.70001", "2026-10-15", [
        t("ACC-01", CORNER, "ACC-E2E-01", "9000.11.00011", "100.00", [], "BBAN with dots, debtor's first txn"),
    ]),
    pmt("P10-B", "12345670001", "2026-10-15", [
        t("ACC-02", CORNER, "ACC-E2E-02", "90001100011", "100.00", [], "same debtor and creditor written without dots: known"),
        t("ACC-03", CORNER, "ACC-E2E-03", "9000 11 00011", "100.00", [], "creditor written with spaces: known"),
        t("ACC-04", CORNER, "ACC-E2E-04", "NO2090001100011", "100.00", [R2], "IBAN of the same creditor is a different key per PO rule (open question)"),
        t("ACC-05", NEG, "ACC-E2E-05", "9000.11.00012", "100.00", [R2], "differs in the last digit: different creditor"),
    ]),
    pmt("P10-C", "NO6012345670001", "2026-10-15", [
        t("ACC-06", CORNER, "ACC-E2E-06", "9000.11.00011", "100.00", [], "debtor as IBAN is a new debtor per PO rule: first txn (open question)"),
    ]),
])

EQVT = '<EqvtAmt><Amt Ccy="EUR">50.00</Amt><CcyOfTrf>NOK</CcyOfTrf></EqvtAmt>'
P11 = ("09", CRE, [
    pmt("P11-A", D11, "2026-10-15", [
        t("ROW-01", POS, "ROW-E2E-01", C_A, "100.00", [], "valid txn before the bad ones"),
        t("ROW-02", NEG, "ROW-E2E-02", None, "100.00", ERR, "CdtrAcct missing: per-transaction error"),
        t("ROW-03", NEG, "ROW-E2E-03", C_A, None, ERR, "EqvtAmt instead of InstdAmt: per-transaction error", amt_xml=EQVT),
        t("ROW-04", NEG, "ROW-E2E-04", C_C, "0.00", ERR, "zero amount: rejected (PO)"),
        t("ROW-05", NEG, "ROW-E2E-05", C_C, "-100.00", ERR, "negative amount: rejected (PO)"),
        t("ROW-06", NEG, "ROW-E2E-06", C_C, "abc", ERR, "non-numeric amount"),
        t("ROW-07", NEG, "ROW-E2E-07", C_C, "100.00", ERR, "InstdAmt without Ccy", amt_xml="<InstdAmt>100.00</InstdAmt>"),
        t("ROW-08", POS, "ROW-E2E-08", C_C, "100.00", [R2], "rejected txns to C_C are not history: C_C still new"),
    ]),
])

P12 = ("09", CRE, [
    pmt("P12-A", D12, "2026-10-15", [
        t("ID-01", POS, "NOTPROVIDED", C_A, "100.00", [], "EndToEndId NOTPROVIDED: InstrId used as id", instr="ID-INS-01"),
        t("ID-02", NEG, "NOTPROVIDED", C_A, "100.00", ERR, "NOTPROVIDED without InstrId: error", tid="", error=["NOTPROVIDED"]),
        t("ID-03", NEG, "NOTPROVIDED", C_A, "100.00", ERR, "NOTPROVIDED without InstrId again: error, not a duplicate of 'NOTPROVIDED'", tid="", error=["NOTPROVIDED"]),
        t("ID-04", CORNER, "NOTPROVIDED", C_A, "200.00", [], "NOTPROVIDED repeated with another InstrId: imported", instr="ID-INS-02"),
        t("ID-05", CORNER, "NOTPROVIDED", C_A, "99999.00", DUP, "NOTPROVIDED repeated with the same InstrId: duplicate, not flagged R1", instr="ID-INS-01"),
        t("ID-06", POS, "ID-E2E-06", C_A, "100.00", [], "EndToEndId wins over InstrId", instr="ID-INS-06"),
        t("ID-07", NEG, "ID-E2E-06", C_A, "99999.00", DUP, "same EndToEndId in the same file: skipped, not flagged R1"),
    ]),
])

P13 = ("03", "2026-10-02T09:00:00", [
    pmt("P13-A", D02, "2026-10-20", [
        t("XB-01", POS, "XB-E2E-01", C_D, "100.00", [R2], "debtor known from an earlier XML import: D is new"),
        t("XB-02", POS, "XB-E2E-02", C_B, "100.00", [], "creditor paid in the earlier import: known"),
        t("XB-03", NEG, "ID-E2E-06", C_A, "100.00", DUP, "EndToEndId imported by an earlier file: skipped"),
        t("XB-04", NEG, "V03-E2E-03", C_A, "100.00", DUP, "id from another debtor's earlier file: skipped"),
    ]),
])

TX_FILES = [
    ("p01_v03_basic.xml", "FILE-P01", POS, "normal .03 file, two PmtInf blocks for one debtor", P01),
    ("p02_v09_basic.xml", "FILE-P02", POS, "normal .09 file, BICFI, two PmtInf blocks with different debtors, Dt and DtTm", P02),
    ("p03_r1_boundaries.xml", "FILE-P03", CORNER, "HIGH_AMOUNT boundaries", P03),
    ("p04_r3_v03.xml", "FILE-P04", CORNER, "FAR_FUTURE_DUE against CreDtTm, .03", P04),
    ("p05_r3_month_end_v09.xml", "FILE-P05", CORNER, "FAR_FUTURE_DUE month-end clamp, .09 Dt and DtTm", P05),
    ("p06_r3_v09.xml", "FILE-P06", CORNER, "FAR_FUTURE_DUE exactly 3 months, .09 Dt and DtTm", P06),
    ("p07_past_due_v03.xml", "FILE-P07", NEG, "due date before CreDtTm, .03", P07),
    ("p08_past_due_v09.xml", "FILE-P08", NEG, "due date before CreDtTm, .09", P08),
    ("p09_currency.xml", "FILE-P09", NEG, "per-currency HIGH_AMOUNT limits (NOK/SEK 10000, EUR 1000) and unsupported currencies", P09),
    ("p10_accounts.xml", "FILE-P10", CORNER, "IBAN vs Othr, BBAN with and without dots", P10),
    ("p11_row_errors.xml", "FILE-P11", NEG, "per-transaction errors, valid txns still imported", P11),
    ("p12_ids.xml", "FILE-P12", CORNER, "NOTPROVIDED / InstrId fallback and duplicates in one file", P12),
    ("p13_second_batch.xml", "FILE-P13", POS, "second batch: R2 and duplicates across files", P13),
]

PREFIXED = ("09", CRE, [pmt("F-PFX", "8601.11.17960", "2026-10-15", [
    t("NSP-01", CORNER, "NSP-E2E-01", C_A, "100.00", [], "ns0: prefixed namespace is the same document: accepted (judgement call)")])])
BOM = ("09", CRE, [pmt("F-BOM", "8601.11.17961", "2026-10-15", [
    t("BOM-01", CORNER, "BOM-E2E-01", C_A, "100.00", [], "UTF-8 BOM before the XML declaration: accepted")])])
ONE_TX = ("09", CRE, [pmt("F-DT", "8601.11.17962", "2026-10-15", [
    t("DTD-01", NEG, "&e2e;", C_A, "100.00", [], "", tid="DTD-E2E-01")])])
ONE_TX_EXT = ("09", CRE, [pmt("F-XXE", "8601.11.17963", "2026-10-15", [
    t("XXE-01", NEG, "&xxe;", C_A, "100.00", [], "", tid="XXE-E2E-01")])])
UNKNOWN = [pmt("F-UNK", "8601.11.17964", "2026-10-15", [t("UNK-01", NEG, "UNK-E2E-01", C_A, "100.00", [], "")])]


def xml_of(spec, **kw):
    version, cre, pmts = spec
    return document(version, cre, pmts, **kw)


def build_file_cases():
    """(file name, bytes, case, category, note, expected summary, error substring or None, accepted tx spec or None)."""
    invalid = xml_of(P01)[:-80]
    return [
        ("f01_unknown_ns_v12.xml", document("12", CRE, UNKNOWN).encode(), "FILE-01", NEG,
         "pain.001.001.12 (not supported yet): whole file rejected", None, "unsupported document type"),
        ("f02_pain008.xml", document("008", CRE, UNKNOWN).encode(), "FILE-02", NEG,
         "pain.008 direct debit: whole file rejected", None, "unsupported document type"),
        ("f03_no_namespace.xml", document("09", CRE, UNKNOWN).replace(f' xmlns="{NS["09"]}"', "").encode(), "FILE-03", NEG,
         "Document without namespace: whole file rejected", None, "unsupported document type"),
        ("f04_invalid_xml.xml", invalid.encode(), "FILE-04", NEG,
         "truncated XML: whole file rejected, nothing imported", None, "not valid XML"),
        ("f05_empty_document.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<Document xmlns="{NS["03"]}"/>\n'.encode(), "FILE-05", CORNER,
         "empty Document: one clear error, nothing imported", None, "no transactions"),
        ("f06_no_pmtinf.xml", document("03", CRE, []).encode(), "FILE-06", CORNER,
         "GrpHdr only, no PmtInf: one clear error, nothing imported", None, "no transactions"),
        ("f07_zero_bytes.xml", b"", "FILE-07", NEG, "0-byte upload: one clear error, no crash", None, "not valid XML"),
        ("f08_binary.xml", b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfebinary", "FILE-08", NEG,
         "binary content with .xml extension: one clear error, no crash", None, None),
        ("f09_doctype_internal_entity.xml",
         xml_of(ONE_TX, doctype='<!DOCTYPE Document [<!ENTITY e2e "DTD-E2E-01">]>\n').encode(), "FILE-09", NEG,
         "DOCTYPE with an internal entity: whole file refused, no crash", None, None),
        ("f10_doctype_external_entity.xml",
         xml_of(ONE_TX_EXT, doctype='<!DOCTYPE Document [<!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]>\n').encode(), "FILE-10", NEG,
         "DOCTYPE with an external (XXE) entity: whole file refused, no file read, no crash", None, None),
        ("f11_prefixed_namespace.xml", xml_of(PREFIXED, ns_prefix="ns0").encode(), "FILE-11", CORNER,
         "ns0: prefixed namespace: accepted like the default namespace (judgement call)", PREFIXED, None),
        ("f12_utf8_bom.xml", b"\xef\xbb\xbf" + xml_of(BOM).encode(), "FILE-12", CORNER,
         "UTF-8 BOM: accepted", BOM, None),
    ]


def summary_of(entries):
    statuses = [e["status"] for e in entries]
    return {"imported": statuses.count("IMPORTED"),
            "flagged": sum(1 for e in entries if e["status"] == "IMPORTED" and e["flags"]),
            "duplicates": statuses.count(DUP), "errors": statuses.count(ERR)}


def step(name, case, cat, note, entries, file_error=None, rejected=False):
    s = summary_of(entries)
    if rejected:
        s = {"imported": 0, "flagged": 0, "duplicates": 0, "errors": 1}
    return {"file": name, "case": case, "category": cat, "note": note, "summary": s,
            "duplicates": [e["transaction_id"] for e in entries if e["status"] == DUP],
            "rejected": rejected, "file_error": file_error,
            "transactions": [dict(e, file=name) for e in entries]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    steps = []
    for name, case, cat, note, spec in TX_FILES:
        (OUT / name).write_text(xml_of(spec), encoding="utf-8")
        steps.append(step(name, case, cat, note, tx_entries(spec[1], spec[2])))

    reupload = [{"case": f"REUP-{i:02d}", "category": NEG, "transaction_id": e["transaction_id"], "status": DUP,
                 "flags": [], "note": f"re-upload of p01: {e['case']} skipped"}
                for i, e in enumerate(steps[0]["transactions"], start=1)]
    steps.append(step("p01_v03_basic.xml", "FILE-REUP", NEG, "same file uploaded again: everything duplicate, nothing re-flagged", reupload))

    for name, content, case, cat, note, accepted, error in build_file_cases():
        (OUT / name).write_bytes(content)
        if accepted:
            steps.append(step(name, case, cat, note, tx_entries(accepted[1], accepted[2])))
        else:
            steps.append(step(name, case, cat, note, [], file_error=error, rejected=True))

    cross_spec = ("09", "2026-10-23T10:00:00", [
        pmt("X-A", "12345678901", "2026-11-15", [
            t("XC-01", POS, "XC-E2E-01", "90001100001", "100.00", [], "CSV debtor 1234.56.78901 paid 9000.11.00001 in all_rules.csv: known"),
            t("XC-02", POS, "XC-E2E-02", "90001100002", "100.00", [R2], "CSV debtor never paid 9000.11.00002: new creditor"),
            t("XC-03", CORNER, "XC-E2E-03", "9000.11.00002", "100.00", [], "paid by XC-02 earlier in this XML: known"),
        ]),
        pmt("X-B", "50001155555", "2026-11-15", [
            t("XC-04", CORNER, "XC-E2E-04", "90001100002", "100.00", [], "CSV debtor 5000.11.55555 paid 9000.11.00002 in all_rules.csv: known"),
            t("XC-05", CORNER, "T-POS-01", "90001100001", "100.00", DUP, "EndToEndId equal to a CSV transaction_id: duplicate across formats"),
        ]),
    ])
    (OUT / "x_cross_csv.xml").write_text(xml_of(cross_spec), encoding="utf-8")
    cross = step("x_cross_csv.xml", "FILE-XC", POS, "imported after all_rules.csv into the same store",
                 tx_entries(cross_spec[1], cross_spec[2]))
    cross["after_csv"] = "all_rules.csv"

    result = {"import_date": IMPORT_DATE, "steps": steps, "cross_format": cross}
    (OUT / "expected_pain001.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    counts = {}
    for s in steps + [cross]:
        counts[s["category"] + " (file)"] = counts.get(s["category"] + " (file)", 0) + 1
        for e in s["transactions"]:
            counts[e["category"]] = counts.get(e["category"], 0) + 1
    print(json.dumps({"steps": len(steps), "cases_by_category": counts}, indent=2))


if __name__ == "__main__":
    main()
