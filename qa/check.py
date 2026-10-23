"""Compare a build's actual results with expected.json.

Usage: python check.py actual.json

actual.json shape (produce it from the build however is easiest):
  {"transactions": [{"transaction_id": "T-R1-02", "flags": ["..."]}, ...],
   "summaries": {"all_rules.csv": {"imported": 31, "flagged": 12, "duplicates": 1, "errors": 0}}}
Both keys are optional, so step 1 (rules engine only) can send just transactions.
Flag codes are the app's own (HIGH_AMOUNT, NEW_CREDITOR, ...); FLAG_ALIASES maps other spellings.
"""
import json
import sys
from pathlib import Path

FLAG_ALIASES = {
    "HIGH_AMOUNT": ["r1"],
    "NEW_CREDITOR": ["r2"],
    "FAR_FUTURE_DUE": ["r3"],
    "UNSUPPORTED_CURRENCY": ["unsupported currency"],
    "PAST_DUE_DATE": ["due date in the past"],
}


def canonical(flag):
    f = str(flag).strip().lower()
    for name, aliases in FLAG_ALIASES.items():
        if f == name.lower() or f in aliases or f.startswith(tuple(a + ":" for a in aliases)):
            return name
    return "UNKNOWN:" + str(flag)


def main(path):
    expected = json.loads((Path(__file__).parent / "expected.json").read_text(encoding="utf-8"))
    actual = json.loads(Path(path).read_text(encoding="utf-8"))
    actual_tx = {t["transaction_id"]: sorted({canonical(f) for f in t.get("flags", [])})
                 for t in actual.get("transactions", [])}
    failures, passed = [], 0

    if actual_tx:
        for e in expected["transactions"]:
            if e["status"] != "IMPORTED":
                continue
            got = actual_tx.get(e["transaction_id"])
            if got is None:
                failures.append(f"[{e['category']}] {e['case']} {e['transaction_id']}: missing from results ({e['note']})")
            elif got != e["flags"]:
                failures.append(f"[{e['category']}] {e['case']} {e['transaction_id']}: expected {e['flags'] or 'no flags'}, "
                                f"got {got or 'no flags'} ({e['note']})")
            else:
                passed += 1

    for file, exp in expected["summaries"].items():
        got = actual.get("summaries", {}).get(file)
        if got is None:
            continue
        diff = {k: (v, got.get(k)) for k, v in exp.items() if got.get(k) != v}
        if diff:
            failures.append(f"SUMMARY {file}: " + ", ".join(f"{k} expected {v[0]} got {v[1]}" for k, v in diff.items()))
        else:
            passed += 1

    for f in failures:
        print("FAIL", f)
    print(f"\n{passed} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
