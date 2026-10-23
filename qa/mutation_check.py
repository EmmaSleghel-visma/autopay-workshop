"""Dependency-free mutation tester: mutates fraud_detection/*.py one change at a time in a temp copy of the repo and reruns the fast QA suite there."""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".hypothesis",
                                ".coverage", "*.db", "htmlcov", "node_modules")
PYTEST = ["-m", "pytest", "-q", "-m", "not slow", "-p", "no:cacheprovider", "-rf",
          "--ignore=tests/qa/test_qa_browser.py", "--continue-on-collection-errors", "--hypothesis-seed=0"]
FAST = ["tests/test_importer.py", "tests/test_rules.py", "tests/qa/test_qa_rules.py", "tests/qa/test_qa_files.py",
        "tests/qa/test_qa_decision_table.py", "tests/qa/test_qa_pipeline.py", "tests/qa/test_qa_properties.py"]
RULES, IMPORTER, MODELS = "fraud_detection/rules.py", "fraud_detection/importer.py", "fraud_detection/models.py"
NOK, SEK, EUR = '"NOK": Decimal("10000.00")', '"SEK": Decimal("10000.00")', '"EUR": Decimal("1000.00")'
FEWER = "if any(v is None for k, v in row.items() if k is not None):"
CLAMP = "min(day.day, calendar.monthrange(year, month)[1])"

MUTANTS = [
    (RULES, "HIGH_AMOUNT: > limit -> >=", "tx.amount > limit:", "tx.amount >= limit:"),
    (RULES, "NOK limit +0.01", NOK, '"NOK": Decimal("10000.01")'),
    (RULES, "NOK limit -0.01", NOK, '"NOK": Decimal("9999.99")'),
    (RULES, "SEK limit +0.01", SEK, '"SEK": Decimal("10000.01")'),
    (RULES, "SEK limit -0.01", SEK, '"SEK": Decimal("9999.99")'),
    (RULES, "EUR limit +0.01", EUR, '"EUR": Decimal("1000.01")'),
    (RULES, "EUR limit -0.01", EUR, '"EUR": Decimal("999.99")'),
    (RULES, "NOK and EUR limits swapped", f"{NOK},\n    {SEK},\n    {EUR},",
     '"NOK": Decimal("1000.00"),\n    ' + SEK + ',\n    "EUR": Decimal("10000.00"),'),
    (RULES, "SEK uses the EUR limit", SEK, '"SEK": Decimal("1000.00")'),
    (RULES, "remove HIGH_AMOUNT append", "flags.append(HIGH_AMOUNT)", "pass"),
    (RULES, "NEW_CREDITOR: and -> or", "history.debtor_known(tx.debtor_account) and not",
     "history.debtor_known(tx.debtor_account) or not"),
    (RULES, "NEW_CREDITOR: drop not", "tx.debtor_account) and not history.has_paid(",
     "tx.debtor_account) and history.has_paid("),
    (RULES, "NEW_CREDITOR: drop debtor_known", "history.debtor_known(tx.debtor_account) and not", "not"),
    (RULES, "remove NEW_CREDITOR append", "flags.append(NEW_CREDITOR)", "pass"),
    (RULES, "FAR_FUTURE months 3 -> 2", "FAR_FUTURE_MONTHS = 3", "FAR_FUTURE_MONTHS = 2"),
    (RULES, "FAR_FUTURE months 3 -> 4", "FAR_FUTURE_MONTHS = 3", "FAR_FUTURE_MONTHS = 4"),
    (RULES, "FAR_FUTURE: > -> >=", "if tx.due_date > _add_months(", "if tx.due_date >= _add_months("),
    (RULES, "remove FAR_FUTURE_DUE append", "flags.append(FAR_FUTURE_DUE)", "pass"),
    (RULES, "start date ignores created_date", "start = tx.created_date if tx.created_date is not None else import_date",
     "start = import_date"),
    (RULES, "start date ignores import_date", "start = tx.created_date if tx.created_date is not None else import_date",
     "start = tx.created_date if tx.created_date is not None else tx.due_date"),
    (RULES, "month clamp removed", CLAMP, "day.day"),
    (RULES, "month clamp -> day 28", CLAMP, "min(day.day, 28)"),
    (RULES, "month end: no clamp, roll over", f"return date(year, month, {CLAMP})",
     "return date(year, month, 1) + __import__('datetime').timedelta(days=day.day - 1)"),
    (RULES, "year overflow guard removed", "if year > date.max.year:", "if False:"),
    (RULES, "PAST_DUE: < -> <=", "if tx.due_date < start:", "if tx.due_date <= start:"),
    (RULES, "remove PAST_DUE_DATE append", "flags.append(PAST_DUE_DATE)", "pass"),
    (RULES, "UNSUPPORTED: SEK removed from supported set", f"    {SEK},\n", ""),
    (RULES, "UNSUPPORTED: USD added to supported set", f"    {EUR},\n", f"    {EUR},\n    \"USD\": Decimal(\"10000.00\"),\n"),
    (RULES, "UNSUPPORTED: is None -> is not None", "if limit is None:", "if limit is not None:"),
    (RULES, "remove UNSUPPORTED_CURRENCY append", "flags.append(UNSUPPORTED_CURRENCY)", "pass"),
    (RULES, "currency lookup lower-cased", "HIGH_AMOUNT_LIMITS.get(tx.currency)",
     "HIGH_AMOUNT_LIMITS.get(tx.currency.lower())"),
    (IMPORTER, "remove currency .upper()", 'currency=values["currency"].upper(),', 'currency=values["currency"],'),
    (IMPORTER, "amount <= 0 -> < 0", "if amount <= 0:", "if amount < 0:"),
    (IMPORTER, "drop non-finite amount check", "if not amount.is_finite():", "if False:"),
    (IMPORTER, "drop missing-column check", "if missing:", "if False:"),
    (IMPORTER, "drop empty-value check", "if empty:", "if False:"),
    (IMPORTER, "drop extra-fields check", "if row.get(None):", "if False:"),
    (IMPORTER, "drop fewer-fields check", FEWER, "if False:"),
    (IMPORTER, "drop row field-count checks (both)", "if row.get(None):", "if False:", FEWER, "if False:"),
    (IMPORTER, "drop value .strip()", '(v or "").strip()', '(v or "")'),
    (IMPORTER, "drop header BOM lstrip", 'h.lstrip("﻿").strip()', "h.strip()"),
    (IMPORTER, "created_date ignored", 'created_date=_parse_date("created_date", created) if created else None',
     "created_date=None"),
    (MODELS, "normalize: remove dot replace", '.replace(".", "")', ""),
    (MODELS, "normalize: remove space replace", '.replace(" ", "")', ""),
    (MODELS, "normalize: remove .strip()", 'return raw.replace(" ", "").replace(".", "").strip()',
     'return raw.replace(" ", "").replace(".", "")'),
]

FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+?)(?: - .*)?$", re.M)


def source_snapshot():
    return {f.name: f.read_bytes() for f in sorted((REPO / "fraud_detection").glob("*.py"))}


def copy_repo(dest):
    shutil.copytree(REPO, dest, ignore=IGNORE)


def run_pytest(workdir, extra=(), timeout=600):
    start = time.perf_counter()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    env.pop("PYTHONPATH", None)
    try:
        proc = subprocess.run([sys.executable, *PYTEST, *extra], cwd=workdir, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return None, set(), time.perf_counter() - start, "timeout"
    out = proc.stdout + proc.stderr
    return proc.returncode, set(FAILED.findall(out)), time.perf_counter() - start, out


def baseline_args(failing):
    args = []
    for nodeid in sorted(failing):
        args += ["--ignore", nodeid] if "::" not in nodeid else ["--deselect", nodeid]
    return args


def check_copy_is_used(workdir):
    probe = Path(workdir) / "tests" / "qa" / "test_zz_mutation_probe.py"
    probe.write_text("import fraud_detection\n\n\ndef test_probe():\n    print('PROBE', fraud_detection.__file__)\n",
                     encoding="utf-8")
    try:
        out = subprocess.run([sys.executable, "-m", "pytest", str(probe), "-q", "-s", "-p", "no:cacheprovider"],
                             cwd=workdir, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    finally:
        probe.unlink()
    found = re.search(r"PROBE (.+)", out)
    if not found or not Path(found.group(1).strip()).resolve().is_relative_to(Path(workdir).resolve()):
        sys.exit(f"pytest in the copy imports fraud_detection from {found and found.group(1)!r}, not {workdir}")


def apply(text, pairs):
    for old, new in pairs:
        if text.count(old) != 1:
            return None, f"pattern found {text.count(old)} times: {old[:50]!r}"
        text = text.replace(old, new)
    return text, ""


def run_mutant(workdir, mutant, extra, timeout):
    path, name, *rest = mutant
    target = (Path(workdir) / path).resolve()
    if not target.is_relative_to(Path(workdir).resolve()):
        sys.exit(f"refusing to write outside the temp copy: {target}")
    original = target.read_text(encoding="utf-8")
    mutated, detail = apply(original, list(zip(rest[::2], rest[1::2])))
    if mutated is None:
        return {"file": path, "name": name, "status": "NOT APPLIED", "killers": [], "seconds": 0.0, "detail": detail}
    target.write_text(mutated, encoding="utf-8", newline="")
    try:
        code, failing, seconds, out = run_pytest(workdir, extra, timeout)
    finally:
        target.write_text(original, encoding="utf-8", newline="")
    if code is None:
        status, detail = "TIMEOUT", f"over {timeout} s"
    elif failing:
        status, detail = "KILLED", ""
    elif code in (0, 5):
        status, detail = "SURVIVED", ""
    elif code in (1, 2, 3, 4):
        status, detail = "KILLED", f"pytest exit code {code}: " + (out.strip().splitlines() or ["?"])[-1][:120]
    else:
        status, detail = "CRASHED", f"interpreter exit code {code}"
    return {"file": path, "name": name, "status": status, "killers": sorted(failing), "seconds": seconds,
            "detail": detail}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-k", default="", help="only mutants whose file or name contains this text")
    parser.add_argument("-j", "--jobs", type=int, default=1, help="parallel workers (one repo copy each)")
    parser.add_argument("--full", action="store_true", help="per mutant: the whole non-slow tests/qa suite, not -x on FAST")
    parser.add_argument("--timeout", type=int, default=120, help="seconds per mutant; a timeout is counted separately")
    args = parser.parse_args()
    mutants = [m for m in MUTANTS if args.k.lower() in f"{m[0]} {m[1]}".lower()]
    before = source_snapshot()

    with tempfile.TemporaryDirectory(prefix="qa-mutation-", ignore_cleanup_errors=True) as tmp:
        workdirs = [Path(tmp) / f"w{i}" for i in range(max(1, min(args.jobs, len(mutants))))]
        for w in workdirs:
            copy_repo(w)
        check_copy_is_used(workdirs[0])

        paths = ["tests/qa"] if args.full else FAST
        code, baseline, seconds, out = run_pytest(workdirs[0], paths, timeout=1800)
        summary = (out.strip().splitlines() or ["?"])[-1] if out != "timeout" else "timeout"
        print(f"baseline ({seconds:.1f} s, {' '.join(paths)}): {summary}", flush=True)
        if code not in (0, 1):
            sys.exit(f"baseline run did not complete (exit code {code}); fix that before mutating")
        for nodeid in sorted(baseline):
            print(f"  pre-existing failure: {nodeid}", flush=True)
        extra = [*baseline_args(baseline), *paths] if args.full else ["-x", *baseline_args(baseline), *paths]
        results = [None] * len(mutants)
        queue = list(enumerate(mutants))

        def worker(workdir):
            while True:
                try:
                    i, m = queue.pop(0)
                except IndexError:
                    return
                results[i] = r = run_mutant(workdir, m, extra, args.timeout)
                print(f"{r['status']:<11} {r['seconds']:5.1f}s  {r['file']}: {r['name']}"
                      + (f"  <- {r['killers'][0]}" if r["killers"] else "")
                      + (f"  ({r['detail']})" if r["detail"] else ""), flush=True)

        with ThreadPoolExecutor(len(workdirs)) as pool:
            list(pool.map(worker, workdirs))

    if source_snapshot() != before:
        sys.exit("fraud_detection/*.py in the real repo changed during the run")
    applied = [r for r in results if r["status"] != "NOT APPLIED"]
    killed = [r for r in applied if r["status"] == "KILLED"]
    survived = [r for r in applied if r["status"] == "SURVIVED"]
    other = [r for r in applied if r["status"] in ("TIMEOUT", "CRASHED")]
    scored = len(killed) + len(survived)
    print(f"\nmutation score: {len(killed)}/{scored} killed = {100 * len(killed) / max(1, scored):.0f}%"
          f" ({len(other)} timed out or crashed, not scored)")
    for r in other:
        print(f"  {r['status']}  {r['file']}: {r['name']} ({r['detail']})")
    for r in survived:
        print(f"  SURVIVED  {r['file']}: {r['name']}")
    for r in results:
        if r["status"] == "NOT APPLIED":
            print(f"  NOT APPLIED  {r['file']}: {r['name']} ({r['detail']})")
    return 0 if not survived else 1


if __name__ == "__main__":
    sys.exit(main())
