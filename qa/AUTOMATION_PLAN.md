# Fraud Detection MVP — test automation plan

Goal: every case in `TEST_PLAN.md` runs automatically on each push, from one source of truth
(`qa/cases.py` → `qa/data/*.csv` + `qa/expected.json`), so adding a case means adding one line there.

Tooling: pytest (already in `requirements-dev.txt`), Flask test client, Playwright for Python for a
few browser checks. Tests live in `tests/qa/` next to the developers' own tests and read
`qa/expected.json`, so expected results are never duplicated in test code.

## Layers

| # | Layer | Entry point | What it covers | Cases | Ready when |
|---|---|---|---|---|---|
| 1 | Rules engine | `rules.evaluate(tx, history, import_date)` with an in-memory `History` | every flag decision, boundaries, combined rules | R1-*, R2-*, R3-*, FMT, MIX, CUR, POS | step 1 (`rules.py`) |
| 2 | Import pipeline | `service.import_transactions()` with `CsvImporter` + a temp SQLite `TransactionStore` | the 3 imports in order: flags per id, summary counts, duplicate ids, error line numbers, cross-import R2 | all transaction cases + SUM, DUP, XIMP, ERR | step 2 |
| 3 | File handling | same, one call per `data/file_*.csv` | header-only, 0 bytes, bad / missing header, `;`, BOM, LF, reordered columns, quoted fields, blank lines, non-CSV | FILE-01..11 | step 2 |
| 4 | Persistence | import, close the store, open a new one on the same file | nothing lost, flags kept, ids still count as duplicates | PERSIST | step 2 |
| 5 | CLI | `python -m fraud_detection import/list` via subprocess, temp `--db` | exit code 0 / 1 on errors, printed summary, list output | smoke | now |
| 6 | Web | Flask test client on `create_app(tmp_db)` | upload each file, summary page numbers, list shows flags + rules, `<script>` escaped, empty / non-CSV upload, same file twice, refresh does not re-import | web cases, XSS-01, SAME-FILE, REFRESH | step 3 |
| 7 | End-user browser | Playwright, Chromium, app started on a free port | 3–5 happy-path journeys as a user: upload → see flags → see summary | POS journeys | step 3 |
| 8 | Performance | pipeline on `file_large_10k.csv` | import < 30 s; list page renders | FILE-12 | step 2, marked `slow` |
| 9 | pain.001 import | `Pain001Importer` (if PO accepts it) | same `expected.json`; `cases.py` also writes the cases as pain.001 XML | all + NOTPROVIDED EndToEndId, batch-level DbtrAcct / ReqdExctnDt | once PO decides + version known |

## How the tests are shaped

- **Data-driven, no hand-written expectations:** each test loads `expected.json`, runs the layer, and
  collects every mismatch before failing (soft assertions), so one run shows all broken cases with
  their case id, category and note — same output as `qa/check.py`.
- **One test per category per layer** (`test_rules_positive`, `test_rules_negative`, `test_rules_corner`, …),
  so the pytest report reads as positive / negative / corner at a glance.
- **Fixed dates:** `import_date` is passed in explicitly (2026-10-23) so R3 cases without
  `created_date` don't change with the calendar. The web layer needs the same seam (an injectable
  clock or `import_date` config) — ask Iulia to add it.
- **Isolation:** every test gets its own temp SQLite file; no shared `fraud_detection.db`.
- **Open questions** (R3 month-end, due < created, non-NOK rules, negative amounts) are marked
  `xfail(strict=False, reason="open with PO")` until answered, then switched to normal asserts.

## CI

GitHub Actions on every push and PR:
- `windows-latest` (the target machine) and `ubuntu-latest`, Python 3.10 and 3.13 (README says 3.10+).
- `python qa/cases.py` first (regenerates data incl. the 10k file), then `pytest -m "not slow"`;
  the slow and Playwright jobs run on PRs to `main` only.
- JUnit XML uploaded as an artifact so failures are readable without the log.

## Order of work

1. Now: layer 5 (CLI smoke) and the shared fixtures (`expected.json` loader, temp store, fake `History`).
2. Step 1 lands: layer 1 — the biggest chunk of value, runs in under a second.
3. Step 2: layers 2, 3, 4, 8.
4. Step 3: layers 6 and 7.
5. CI workflow as soon as layer 1 is green.
6. pain.001: after the PO decision and a scrubbed sample from customer-mikael.

## Needs from the team

- Write access to `EmmaSleghel-visma/autopay-workshop` (or a PR from a fork) to push `qa/` and `tests/qa/`.
- Iulia: an `import_date` seam in the web layer; stable element ids or `data-testid`s on the upload form, summary numbers and flag cells.
- PO: the four open rule questions; pain.001 in or out.
