# Fraud Detection MVP - Pilot Guide

The app checks your payment files and flags transactions that may be fraudulent, so you can review them before paying.
It runs on your own Windows PC and you use it in your web browser.

## 1. Install (once)

1. Install **Python 3.10 or newer** from python.org. In the installer, tick **"Add python.exe to PATH"**.
2. Unzip the app folder you received from us, for example to `C:\FraudDetection`.
3. Open that folder, click the address bar, type `cmd` and press Enter. In the black window, paste:
   ```
   py -3 -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
   This downloads the app's components once. Afterwards the app needs no internet connection.

## 2. Start the app

In the same black window (open it as in step 3 above), paste:
```
.venv\Scripts\flask --app "fraud_detection.web:create_app()" run
```
Then open **http://127.0.0.1:5000** in your browser. Keep the black window open while you use the app; close it to stop the app.

## 3. Import a file

> **Note:** the upload page is in the next build. This section will be completed when it ships.

Supported files:
- **CSV**, UTF-8, with the columns `transaction_id, debtor_account, creditor_account, amount, currency, due_date, created_date` (`created_date` optional, dates as `YYYY-MM-DD`, `.` as decimal separator). In Excel, save as **"CSV UTF-8"**.
- **ISO 20022 pain.001** XML, versions 001.001.03 and 001.001.09.

After each import you see a summary: how many transactions were **imported**, **flagged**, skipped as **duplicates** (already imported earlier), and **errors** (rows that could not be read, with the line or transaction and the reason). Fix the rows with errors and import them again; already imported transactions are skipped automatically.

## 4. What the flags mean

| Flag | Meaning |
|---|---|
| HIGH_AMOUNT | Amount is above 10 000 NOK |
| NEW_CREDITOR | This payer has paid before, but never to this receiving account |
| FAR_FUTURE_DUE | Due date is more than 3 months after the transaction was created (or imported) |
| PAST_DUE_DATE | Due date is before the date the transaction was created (or imported) |
| UNSUPPORTED_CURRENCY | Currency is not NOK; amounts are not converted, so check it manually |

A flag means **"check this"**, not "this is fraud". Before the payment is sent, confirm it with the person who requested it, using contact details you already have, not the ones on the invoice. The app never blocks or changes a payment.

## 5. Your data and security

- **Stays on your PC.** Transactions are stored only in the file `fraud_detection.db` in the app folder.
- **Nothing is sent anywhere.** The app makes no network connections and shares no data with us or anyone else.
- **Only reachable from your own PC.** The browser page answers only on `127.0.0.1`; other computers on your network cannot open it.
- **Not encrypted, no login.** Anyone who can use your Windows account can open the app and the data file. Protect it with a Windows password, and BitLocker disk encryption if your company uses it.
- **Backup:** stop the app, then copy `fraud_detection.db` to a safe place. To restore, copy it back.
- **Delete all data:** stop the app and delete `fraud_detection.db` (and any backups). When the pilot ends, delete the whole app folder.

## 6. Known limitations (MVP)

- Windows PC, one user at a time; no user accounts.
- CSV and pain.001 only. JSON import is planned for the pilot phase.
- NOK only: other currencies are flagged, not converted.
- Flags are rule-based and simple; they will not catch every fraud and will sometimes flag normal payments.
- A row with fewer values than the header is currently accepted; this may change.

## 7. Feedback and problems

Contact your Autopay contact. For a problem, tell us what you did, what you expected and what happened, and include the file (with sensitive data removed) and a screenshot of the summary.
