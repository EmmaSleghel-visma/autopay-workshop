# Fraud Detection MVP — quality report

Measured 2026-10-23 on the QA laptop (Windows 11, Python 3.13, `.venv`), branch `qa/automated-tests`.

## 1. Performance (`tests/qa/test_qa_performance.py`)

`pytest tests/qa/test_qa_performance.py -m slow -q -s` — generated CSV files (NOK, 500 debtors,
2000 creditors, seeded), imported through `import_transactions` into a fresh SQLite file. Import time
is a plain run; peak memory is a second run under `tracemalloc`; `all()` is `store.all()` afterwards.

| rows | import s (run 1 / run 2) | rows/s | tracemalloc peak MB | `store.all()` s |
|-----:|-------------------------:|-------:|--------------------:|----------------:|
| 10,000 | 0.18 / 0.42 | 24k–57k | 5.0 | 0.05 / 0.13 |
| 100,000 | 2.28 / 3.38 | 30k–44k | 49.9 | 0.62 / 0.73 |
| 1,000,000 | skipped unless `QA_HUGE=1` | | | |

Ceilings in the test (catch an order-of-magnitude regression, not normal noise):

| rows | max import s | max peak MB | max `all()` s | margin over worst measured |
|-----:|-------------:|------------:|--------------:|---------------------------:|
| 10,000 | 5 | 25 | 1 | 12x time, 5x memory, 8x list |
| 100,000 | 30 | 250 | 8 | 9x time, 5x memory, 11x list |
| 1,000,000 | 300 | 2500 | 80 | extrapolated linearly (not measured) |

Memory scales linearly (~0.5 KB per row): the whole file is parsed into memory before storing, so a
1M-row file needs ~500 MB of Python objects. Fine for the MVP; streaming would be needed beyond that.

## 2. Mutation testing (`qa/mutation_check.py`)

Copies the repo to a temp dir, applies one mutation at a time to `fraud_detection/*.py` in the copy
and runs pytest there. The real `fraud_detection/*.py` are snapshotted before and compared after the
run (the script aborts if they changed); they were unchanged.

**Scope of the run (time):** the default mode runs each mutant with `-x` on the fast relevant subset
`tests/test_importer.py tests/test_rules.py tests/qa/test_qa_rules.py tests/qa/test_qa_files.py
tests/qa/test_qa_decision_table.py tests/qa/test_qa_pipeline.py tests/qa/test_qa_properties.py`,
120 s timeout per mutant (timeouts/crashes are counted separately, not as kills). The
state/concurrency tests (`tests/qa/test_qa_state.py`) were **excluded** from mutation runs: unmutated
they take ~80 s, and under 4 parallel workers they made each full-suite mutant run 2–8 minutes.
`--full` runs the whole non-slow `tests/qa` suite per mutant instead.

Baseline (unmutated copy, fast subset): 66 passed, 0 failing. On the full non-slow `tests/qa` suite the
baseline has 5 failing tests in `test_qa_state.py` (real app findings, see section 4); a mutant only
counts as killed when it makes an additional test fail.

**Score: 42 / 45 killed = 93 %** on the fast subset (31 rules, 11 importer, 3 models mutants;
0 timeouts after moving the cheap unit tests to the front of the `-x` run).
With `tests/test_service.py` and `tests/qa/test_qa_fuzz.py` added it is 43 / 45 = 96 % (verified by hand).

Every mutation asked for is killed: HIGH_AMOUNT `>` -> `>=`; NOK/SEK/EUR limits ±0.01, NOK/EUR swapped,
SEK given the EUR limit; NEW_CREDITOR `and` -> `or`, dropped `not`, dropped `debtor_known`;
FAR_FUTURE months 3 -> 2 and 3 -> 4, `>` -> `>=`; month clamp removed / day 28 / roll-over;
PAST_DUE `<` -> `<=`; supported set without SEK, with USD, `is None` inverted; each of the five flag
appends removed; currency `.upper()` removed; normalize dot/space replace removed; amount `<= 0` ->
`< 0`; extra-fields and fewer-fields row checks removed (each and both); missing-column, empty-value,
value `.strip()`, header BOM and `created_date` mutants.

Surviving mutants and the test that would kill them:

| mutant | why it survives | test that kills it |
|--------|-----------------|--------------------|
| `rules._add_months`: `if year > date.max.year` guard removed | only the 9999 edge reaches it | already killed by `tests/test_service.py::test_created_date_near_year_9999_does_not_crash_the_import` and `tests/qa/test_qa_fuzz.py::test_extreme_dates_through_pipeline` — just outside the fast subset |
| `importer._parse_amount`: `if not amount.is_finite()` removed | no deterministic test feeds `NaN`/`Infinity` to the CSV importer; with the check gone `NaN` raises an uncaught `decimal.InvalidOperation` and `Infinity` is imported as an amount | add to `tests/test_importer.py`: amounts `NaN`, `sNaN`, `Infinity`, `-Infinity` each give a row error "amount is not a number" and no transaction |
| `models.normalize_account`: trailing `.strip()` removed | near-equivalent: the CSV importer already strips every value and `replace(" ", "")` removes spaces, so only tabs/newlines inside the raw value would differ | unit test `normalize_account("\t1234.56.78903\n") == "12345678903"` (or drop the redundant `.strip()`) |

## 3. Coverage of `fraud_detection/`

`pytest tests -m "not slow" --cov=fraud_detection --cov-branch --cov-report=term-missing -p no:cacheprovider --ignore=tests/qa/test_qa_browser.py`
had to be run with `--deselect tests/qa/test_qa_state.py::test_two_threads_sharing_one_store_import_into_the_same_db`:
with coverage tracing on, that test crashes the interpreter (Windows access violation inside
`sqlite3` in `storage.exists`, two threads sharing one `check_same_thread=False` connection).
Result: 165 passed, 4 failed (the known `test_qa_state.py` findings), 6 min 43 s.

| module | stmts | miss | branches | partial | cover |
|--------|------:|-----:|---------:|--------:|------:|
| `__main__.py` | 50 | 6 | 12 | 2 | 87 % |
| `importer.py` | 62 | 1 | 12 | 1 | 97 % |
| `models.py` | 29 | 0 | 0 | 0 | 100 % |
| `pain001.py` | 80 | 5 | 28 | 3 | 93 % |
| `rules.py` | 33 | 0 | 12 | 0 | 100 % |
| `service.py` | 33 | 0 | 6 | 0 | 100 % |
| `storage.py` | 38 | 0 | 2 | 0 | 100 % |
| `web/__init__.py` | 30 | 0 | 2 | 0 | 100 % |
| **total** | **355** | **12** | **74** | **6** | **96 %** (lines 96.6 %, branches ≈ 92 %) |

Notable uncovered lines:

- `importer.py:87` — the non-finite amount error (same gap as the surviving mutant above).
- `pain001.py:72, 74` — "debtor account (DbtrAcct) missing" and "requested execution date missing" errors.
- `pain001.py:115, 125-126` — `_due_date` with no `ReqdExctnDt` node and `_date_part` with an unparsable date.
- `__main__.py:26-28, 33` — the "rules engine not implemented" fallback (dead now that rules exist);
  `46-47` — `list` on an empty store. The CLI tests run it in a subprocess, which coverage does not trace.

## 4. Open findings from the suite

- `test_qa_state.py`: 5 failing on the unmutated code — two CLI processes (or two threads with own
  connections) importing into the same DB fail with `IntegrityError: UNIQUE constraint failed` and lose
  rows; a corrupt DB file gives a traceback instead of a clear error; two threads sharing one store
  fail and, under coverage tracing, crash the interpreter.

## 5. Recommendations

1. Add the `NaN`/`Infinity` importer unit tests (kills the surviving mutant, covers `importer.py:87`).
2. Add pain.001 tests for missing `DbtrAcct`, missing/unparsable `ReqdExctnDt`.
3. Decide on concurrency: either serialize imports (e.g. `BEGIN IMMEDIATE` + duplicate check inside the
   transaction / `INSERT OR IGNORE`) or document "one import at a time"; drop `check_same_thread=False`
   or guard the shared connection with a lock.
4. Remove the dead `NotImplementedError` fallback in `__main__.py` and the redundant `.strip()` in
   `normalize_account`.
5. Keep `test_qa_state.py` out of mutation runs, and run `qa/mutation_check.py --full` only nightly.

> Update (after merging main 71376c4): the concurrency / corrupt-DB failures listed above were fixed in PR #2 (9fcd76e); the full non-slow suite now passes (180 passed), so recommendation 3 is done.
