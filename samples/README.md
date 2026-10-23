# Sample transactions

`transactions.csv` is synthetic test data. Expected result when imported into an empty database:

| Row | ID | What it exercises | Expected |
|---|---|---|---|
| 2 | T001 | debtor's first transaction | not flagged |
| 3 | T002 | same creditor, written with spaces instead of dots | not flagged (normalised accounts match) |
| 4 | T003 | known debtor pays a new creditor | NEW_CREDITOR |
| 5 | T004 | exactly 10 000.00 NOK | not flagged |
| 6 | T005 | 10 000.01 NOK | HIGH_AMOUNT |
| 7 | T006 | due exactly 3 months after created_date (22 Oct -> 22 Jan) | not flagged |
| 8 | T007 | due 3 months + 1 day after created_date | FAR_FUTURE_DUE |
| 9 | T008 | no created_date, so rule 3 counts from the import date | depends on import date |
| 10 | T009 | USD (not NOK, SEK or EUR) | UNSUPPORTED_CURRENCY |
| 11 | T010 | 25 000 NOK, due 4+ months out | HIGH_AMOUNT, FAR_FUTURE_DUE |
| 12 | T001 | same transaction_id again | skipped, reported as duplicate |
| 13 | T011 | amount `abc` | rejected, error on line 13 |
| 14 | T012 | due date not YYYY-MM-DD | rejected, error on line 14 |

Totals: 10 imported, 2 errors, 1 duplicate.

## pain001_v03.xml

Synthetic pain.001.001.03 file from QA (razvan-agent), modelled on the pilot customer's export. Expected on an empty database, imported 2026-10-23:

| ID | Expected flags |
|---|---|
| E2E-0001 | none (debtor's first transaction) |
| E2E-0002 | HIGH_AMOUNT, NEW_CREDITOR |
| E2E-0003 | NEW_CREDITOR (EUR 650 is below the EUR 1 000 limit) |
| E2E-0004 | FAR_FUTURE_DUE (second PmtInf block, due 2027-03-01) |
