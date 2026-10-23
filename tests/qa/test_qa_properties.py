"""Hypothesis property tests on rules.evaluate plus a differential test of the real import pipeline against the oracle."""

import csv
import io
import tempfile
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fraud_detection import rules
from fraud_detection.importer import CsvImporter
from fraud_detection.models import Transaction, normalize_account
from fraud_detection.service import import_transactions
from fraud_detection.storage import TransactionStore
from oracle import clean_account, replay, three_months_later
from qa_support import IMPORT_DATE

FAST = settings(max_examples=250, deadline=None, derandomize=True)
DIFFERENTIAL = settings(max_examples=200, deadline=None, derandomize=True,
                        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])

DEBTORS = ["12345678903", "98765432109", "15030012345"]
CREDITORS = ["11112222333", "44445555666", "77778888999"]
FOREIGN = ["EUR", "SEK", "USD", "DKK", "NOKK", "NO"]
MONTH_ENDS = [
    date(2024, 1, 31), date(2024, 2, 29), date(2023, 11, 30), date(2023, 11, 29),
    date(2023, 12, 31), date(2025, 11, 30), date(2027, 11, 30), date(2027, 11, 29),
    date(2026, 8, 31), date(2026, 5, 31), date(2028, 2, 29), date(2027, 2, 28),
    date(2026, 10, 31), date(2026, 3, 31), date(2025, 12, 31),
]

amounts = st.one_of(
    st.sampled_from([Decimal("10000.00"), Decimal("10000.01"), Decimal("9999.99"), Decimal("0.01")]),
    st.integers(min_value=1, max_value=2_000_000).map(lambda c: Decimal(c) / 100),
)
start_dates = st.one_of(
    st.sampled_from(MONTH_ENDS),
    st.dates(min_value=date(2023, 10, 1), max_value=date(2028, 3, 31)),
)
currencies = st.one_of(st.just("NOK"), st.sampled_from(FOREIGN))


class FakeHistory:
    def __init__(self, pairs=()):
        self.pairs = frozenset(pairs)

    def debtor_known(self, debtor_account):
        return any(d == debtor_account for d, _ in self.pairs)

    def has_paid(self, debtor_account, creditor_account):
        return (debtor_account, creditor_account) in self.pairs


@st.composite
def due_for(draw, start):
    limit = three_months_later(start)
    return draw(st.one_of(
        st.sampled_from([limit, limit + timedelta(days=1), limit - timedelta(days=1),
                         start, start - timedelta(days=1), start + timedelta(days=1)]),
        st.integers(min_value=-60, max_value=140).map(lambda d: start + timedelta(days=d)),
    ))


@st.composite
def transactions(draw):
    created = draw(st.one_of(st.none(), start_dates))
    start = created if created is not None else IMPORT_DATE
    return Transaction(
        transaction_id="P1",
        debtor_account=draw(st.sampled_from(DEBTORS)),
        creditor_account=draw(st.sampled_from(CREDITORS)),
        amount=draw(amounts),
        currency=draw(currencies),
        due_date=draw(due_for(start)),
        created_date=created,
    )


histories = st.frozensets(st.tuples(st.sampled_from(DEBTORS), st.sampled_from(CREDITORS)), max_size=6).map(FakeHistory)


@st.composite
def formatted(draw, account):
    out = []
    for ch in account:
        out.append(draw(st.sampled_from(["", "", " ", ".", "  ", ". "])))
        out.append(ch)
    out.append(draw(st.sampled_from(["", " ", "."])))
    return "".join(out)


@FAST
@given(transactions(), histories)
def test_high_amount_iff_amount_above_limit(tx, history):
    flagged = rules.HIGH_AMOUNT in rules.evaluate(tx, history, IMPORT_DATE)
    assert flagged == (tx.amount > Decimal("10000.00")), f"amount={tx.amount}"


@FAST
@given(transactions(), histories)
def test_first_transaction_of_debtor_never_new_creditor(tx, history):
    others = FakeHistory({p for p in history.pairs if p[0] != tx.debtor_account})
    assert rules.NEW_CREDITOR not in rules.evaluate(tx, others, IMPORT_DATE)


@FAST
@given(transactions(), histories)
def test_new_creditor_iff_known_debtor_never_paid_creditor(tx, history):
    known = any(d == tx.debtor_account for d, _ in history.pairs)
    paid = (tx.debtor_account, tx.creditor_account) in history.pairs
    flagged = rules.NEW_CREDITOR in rules.evaluate(tx, history, IMPORT_DATE)
    assert flagged == (known and not paid)


@FAST
@given(st.data(), transactions(), histories)
def test_flags_independent_of_account_formatting(data, tx, history):
    tx_debtor = data.draw(formatted(tx.debtor_account))
    tx_creditor = data.draw(formatted(tx.creditor_account))
    hist_pairs = set()
    for d, c in history.pairs:
        hist_pairs.add((normalize_account(data.draw(formatted(d))), normalize_account(data.draw(formatted(c)))))
    reformatted = replace(tx, debtor_account=normalize_account(tx_debtor),
                          creditor_account=normalize_account(tx_creditor))
    assert normalize_account(tx_debtor) == clean_account(tx_debtor) == tx.debtor_account
    got = rules.evaluate(reformatted, FakeHistory(hist_pairs), IMPORT_DATE)
    assert sorted(got) == sorted(rules.evaluate(tx, history, IMPORT_DATE))


@FAST
@given(transactions(), histories, st.sampled_from(FOREIGN))
def test_foreign_currency_adds_only_unsupported_currency(tx, history, foreign):
    nok = rules.evaluate(replace(tx, currency="NOK"), history, IMPORT_DATE)
    other = rules.evaluate(replace(tx, currency=foreign), history, IMPORT_DATE)
    assert rules.UNSUPPORTED_CURRENCY not in nok
    assert rules.UNSUPPORTED_CURRENCY in other
    assert sorted(set(other) - {rules.UNSUPPORTED_CURRENCY}) == sorted(nok)


@FAST
@given(transactions(), histories)
def test_far_future_and_past_due_never_both(tx, history):
    got = rules.evaluate(tx, history, IMPORT_DATE)
    assert not (rules.FAR_FUTURE_DUE in got and rules.PAST_DUE_DATE in got)


@FAST
@given(transactions(), histories)
def test_due_on_start_has_neither_date_flag(tx, history):
    start = tx.created_date if tx.created_date is not None else IMPORT_DATE
    got = rules.evaluate(replace(tx, due_date=start), history, IMPORT_DATE)
    assert rules.FAR_FUTURE_DUE not in got and rules.PAST_DUE_DATE not in got


@FAST
@given(transactions(), histories)
def test_date_flags_match_calendar_month_limit(tx, history):
    start = tx.created_date if tx.created_date is not None else IMPORT_DATE
    got = rules.evaluate(tx, history, IMPORT_DATE)
    assert (rules.FAR_FUTURE_DUE in got) == (tx.due_date > three_months_later(start)), \
        f"start={start} due={tx.due_date} limit={three_months_later(start)}"
    assert (rules.PAST_DUE_DATE in got) == (tx.due_date < start), f"start={start} due={tx.due_date}"


@FAST
@given(transactions(), histories)
def test_result_has_no_duplicates_and_only_known_codes(tx, history):
    got = rules.evaluate(tx, history, IMPORT_DATE)
    assert len(got) == len(set(got))
    assert set(got) <= {rules.HIGH_AMOUNT, rules.NEW_CREDITOR, rules.FAR_FUTURE_DUE,
                        rules.PAST_DUE_DATE, rules.UNSUPPORTED_CURRENCY}


@FAST
@given(transactions(), histories)
def test_evaluate_does_not_mutate_history(tx, history):
    before = set(history.pairs)
    tx_before = replace(tx)
    rules.evaluate(tx, history, IMPORT_DATE)
    assert set(history.pairs) == before
    assert tx == tx_before


@st.composite
def csv_rows(draw):
    count = draw(st.integers(min_value=1, max_value=12))
    rows = []
    for i in range(count):
        created = draw(st.one_of(st.none(), start_dates))
        start = created if created is not None else IMPORT_DATE
        tx_id = draw(st.sampled_from([r["transaction_id"] for r in rows])) if rows and draw(
            st.integers(0, 9)) == 0 else f"T{i}"
        rows.append({
            "transaction_id": tx_id,
            "debtor_account": draw(formatted(draw(st.sampled_from(DEBTORS[:2])))),
            "creditor_account": draw(formatted(draw(st.sampled_from(CREDITORS[:2])))),
            "amount": draw(amounts).quantize(Decimal("0.01")),
            "currency": draw(st.one_of(st.sampled_from(["NOK", "nok"]), st.sampled_from(FOREIGN))),
            "due_date": draw(due_for(start)),
            "created_date": created,
        })
    return rows


def to_csv(rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["transaction_id", "debtor_account", "creditor_account", "amount", "currency",
                     "due_date", "created_date"])
    for r in rows:
        writer.writerow([r["transaction_id"], r["debtor_account"], r["creditor_account"], str(r["amount"]),
                         r["currency"], r["due_date"].isoformat(),
                         r["created_date"].isoformat() if r["created_date"] else ""])
    return out.getvalue()


def run_pipeline(batches):
    with tempfile.TemporaryDirectory() as tmp:
        store = TransactionStore(Path(tmp) / "diff.db")
        try:
            errors = []
            for text in batches:
                summary = import_transactions(io.StringIO(text, newline=""), CsvImporter(), store,
                                              rules.evaluate, IMPORT_DATE)
                errors.extend(summary.errors)
            return {s.transaction.transaction_id: sorted(s.flags) for s in store.all()}, errors
        finally:
            store.close()


@DIFFERENTIAL
@given(csv_rows(), st.integers(min_value=0, max_value=12))
def test_pipeline_matches_oracle(rows, split):
    split = min(split, len(rows))
    actual, errors = run_pipeline([to_csv(rows[:split]), to_csv(rows[split:])])
    expected = replay(rows, IMPORT_DATE)
    assert not errors, errors
    failures = [f"{tx_id}: expected {expected.get(tx_id)}, got {actual.get(tx_id)}"
                for tx_id in sorted(set(expected) | set(actual)) if expected.get(tx_id) != actual.get(tx_id)]
    assert not failures, "\n".join(failures)
