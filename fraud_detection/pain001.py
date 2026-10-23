"""ISO 20022 pain.001 (customer credit transfer initiation) importer, versions .03 and .09.

Mapping (agreed with the pilot customer):
- transaction_id   CdtTrfTxInf/PmtId/EndToEndId, or InstrId when EndToEndId is 'NOTPROVIDED'
- debtor_account   PmtInf/DbtrAcct (IBAN or Othr/Id), shared by every transaction in the PmtInf
- creditor_account CdtTrfTxInf/CdtrAcct (IBAN or Othr/Id); optional in the schema, required here
- amount, currency CdtTrfTxInf/Amt/InstdAmt and its Ccy attribute (EqvtAmt is not supported)
- due_date         PmtInf/ReqdExctnDt (.03: a date; .09: Dt, or DtTm whose date part is used)
- created_date     GrpHdr/CreDtTm, date part
"""

import xml.etree.ElementTree as ET
from datetime import date
from typing import TextIO

from .importer import _parse_amount
from .models import ParseResult, RowError, Transaction, normalize_account

SUPPORTED_NAMESPACES = {
    "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03",
    "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09",
}


class Pain001Importer:
    """Errors carry line=0 (no line numbers); the message names the transaction instead."""

    def parse(self, source: TextIO) -> ParseResult:
        result = ParseResult()
        text = source.read()
        # A pain.001 never needs a DTD; refusing any DOCTYPE closes the whole entity/XXE class.
        if "<!DOCTYPE" in text:
            result.errors.append(RowError(0, "file contains a DOCTYPE declaration, which pain.001 files never need"))
            return result
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            result.errors.append(RowError(0, f"not valid XML: {exc}"))
            return result

        ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else ""
        if ns not in SUPPORTED_NAMESPACES:
            result.errors.append(RowError(0, f"unsupported document type: {ns or root.tag!r} "
                                             "(expected pain.001.001.03 or .09)"))
            return result
        q = lambda path: "/".join(f"{{{ns}}}{p}" for p in path.split("/"))

        initiation = root.find(q("CstmrCdtTrfInitn"))
        created = _date_part(_text(initiation, q("GrpHdr/CreDtTm"))) if initiation is not None else None

        number = 0
        for pmt_inf in root.iterfind(q("CstmrCdtTrfInitn/PmtInf")):
            pmt_id = _text(pmt_inf, q("PmtInfId")) or "?"
            debtor = _account(pmt_inf.find(q("DbtrAcct")), q)
            due = _due_date(pmt_inf.find(q("ReqdExctnDt")), q)
            for tx in pmt_inf.iterfind(q("CdtTrfTxInf")):
                number += 1
                tx_id = _transaction_id(tx, q)
                label = f"transaction {number} ({tx_id or 'no id'}, PmtInf {pmt_id})"
                try:
                    result.transactions.append(self._build(tx, q, tx_id, debtor, due, created))
                except ValueError as exc:
                    result.errors.append(RowError(0, f"{label}: {exc}"))
        if number == 0:
            result.errors.append(RowError(0, "no transactions (CdtTrfTxInf) found"))
        return result

    def _build(self, tx, q, tx_id, debtor, due, created) -> Transaction:
        if not tx_id:
            raise ValueError("EndToEndId is NOTPROVIDED and there is no InstrId")
        if not debtor:
            raise ValueError("debtor account (DbtrAcct) missing")
        if due is None:
            raise ValueError("requested execution date (ReqdExctnDt) missing or not a date")
        creditor = _account(tx.find(q("CdtrAcct")), q)
        if not creditor:
            raise ValueError("creditor account (CdtrAcct) missing")
        instd = tx.find(q("Amt/InstdAmt"))
        if instd is None:
            raise ValueError("only Amt/InstdAmt is supported (EqvtAmt needs currency conversion)")
        currency = (instd.get("Ccy") or "").strip().upper()
        if not currency:
            raise ValueError("InstdAmt has no Ccy attribute")
        return Transaction(
            transaction_id=tx_id,
            debtor_account=normalize_account(debtor),
            creditor_account=normalize_account(creditor),
            amount=_parse_amount((instd.text or "").strip()),
            currency=currency,
            due_date=due,
            created_date=created,
        )


def _text(node, path) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def _account(acct, q) -> str:
    if acct is None:
        return ""
    return _text(acct, q("Id/IBAN")) or _text(acct, q("Id/Othr/Id"))


def _transaction_id(tx, q) -> str:
    end_to_end = _text(tx, q("PmtId/EndToEndId"))
    if end_to_end and end_to_end != "NOTPROVIDED":
        return end_to_end
    return _text(tx, q("PmtId/InstrId"))


def _due_date(node, q) -> date | None:
    if node is None:
        return None
    # .03: <ReqdExctnDt>2026-11-15</ReqdExctnDt>; .09: <ReqdExctnDt><Dt>..</Dt></ReqdExctnDt> or <DtTm>
    raw = (node.text or "").strip() or _text(node, q("Dt")) or _text(node, q("DtTm"))
    return _date_part(raw)


def _date_part(raw: str) -> date | None:
    """ISODate and ISODateTime both start with YYYY-MM-DD."""
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None
