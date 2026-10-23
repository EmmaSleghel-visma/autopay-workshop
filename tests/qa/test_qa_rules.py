"""Layer 1: rules.evaluate() alone, with an in-memory History, replaying all_rules.csv in file order."""

from fraud_detection import rules
from fraud_detection.importer import CsvImporter
from qa_support import DATA_DIR, IMPORT_DATE, flag_mismatches


class InMemoryHistory:
    def __init__(self):
        self.pairs = set()

    def debtor_known(self, debtor_account):
        return any(d == debtor_account for d, _ in self.pairs)

    def has_paid(self, debtor_account, creditor_account):
        return (debtor_account, creditor_account) in self.pairs


def evaluate_all_rules_file():
    with open(DATA_DIR / "all_rules.csv", newline="", encoding="utf-8-sig") as f:
        parsed = CsvImporter().parse(f)
    history, flags = InMemoryHistory(), {}
    for tx in parsed.transactions:
        if tx.transaction_id in flags:
            continue
        flags[tx.transaction_id] = rules.evaluate(tx, history, IMPORT_DATE)
        history.pairs.add((tx.debtor_account, tx.creditor_account))
    return flags


def only_all_rules(expected):
    return {**expected, "transactions": [e for e in expected["transactions"] if e["file"] == "all_rules.csv"]}


def test_rules_positive(expected):
    failures = flag_mismatches(only_all_rules(expected), "POS", evaluate_all_rules_file())
    assert not failures, "\n".join(failures)


def test_rules_negative(expected):
    failures = flag_mismatches(only_all_rules(expected), "NEG", evaluate_all_rules_file())
    assert not failures, "\n".join(failures)


def test_rules_corner(expected):
    failures = flag_mismatches(only_all_rules(expected), "CORNER", evaluate_all_rules_file())
    assert not failures, "\n".join(failures)
