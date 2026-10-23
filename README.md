# autopay-workshop

## Fraud Detection MVP

Browser-based app that imports payment transactions from CSV and flags potentially fraudulent ones.

### Layout

| Path | What | Owner |
|---|---|---|
| `fraud_detection/models.py` | `Transaction`, `History` protocol, account normalisation | Developer |
| `fraud_detection/importer.py` | `Importer` protocol + `CsvImporter` | Developer |
| `fraud_detection/storage.py` | SQLite `TransactionStore` (also the rules' `History`) | Developer |
| `fraud_detection/service.py` | Import pipeline: parse → skip duplicates → evaluate → store | Developer |
| `fraud_detection/rules.py` | Rules engine (`evaluate`) - contract in the docstring | Iulia |
| `fraud_detection/web/` | Flask app factory + pages | Iulia |

### CSV format

Header row required, comma-separated, `.` as decimal separator, dates as `YYYY-MM-DD`:

```
transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date
t1,1234.56.78903,9876.54.32109,10000.01,NOK,2026-11-30,2026-10-01
```

`created_date` is optional. Account numbers are compared with spaces and dots removed.
A `transaction_id` that was already imported is skipped and reported as a duplicate.
Zero and negative amounts are rejected.

### ISO 20022 pain.001 (`.xml` files)

Versions `pain.001.001.03` and `.09` are supported (`fraud_detection/pain001.py`, mapping in its docstring):
`EndToEndId` (or `InstrId` when it is `NOTPROVIDED`) → transaction_id, `PmtInf/DbtrAcct` → debtor,
`CdtrAcct` → creditor, `InstdAmt` + `Ccy` → amount/currency, `PmtInf/ReqdExctnDt` → due date,
`GrpHdr/CreDtTm` → created date. A transaction without `CdtrAcct`, or with `EqvtAmt`, is reported as an error.
History is shared with CSV imports, so the same accounts match across both formats.

### Run on Windows

Double-click `start.bat` (needs Python 3.10+ installed; sets up `.venv` on first start, then opens the browser). Or by hand:

```
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\flask --app "fraud_detection.web:create_app()" run
```

Then open http://127.0.0.1:5000. Data is stored in `fraud_detection.db` (override with the `FRAUD_DB` environment variable).

### Try it from the command line

```
.venv\Scripts\python -m fraud_detection import samples\transactions.csv
.venv\Scripts\python -m fraud_detection import samples\pain001_v03.xml
.venv\Scripts\python -m fraud_detection list
```

`samples/README.md` lists what each sample row exercises and the expected result.

### Tests

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pytest
```

On macOS/Linux use `.venv/bin/` instead of `.venv\Scripts\`. Requires Python 3.10+.
