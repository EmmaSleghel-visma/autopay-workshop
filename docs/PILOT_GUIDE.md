# Fraud Detection MVP - Pilot Guide

The app checks your payment files and flags transactions that may be fraudulent, so you can review them before paying.
It runs on your own Windows PC and you use it in your web browser.

## 1. Install (once)

1. Install **Python 3.10 or newer** from python.org ("Download Python", run the installer, keep the default options).
2. Right-click the zip you received from us, choose **Extract All...** and extract it, for example to `C:\`.
   The zip contains one folder; the **app folder** is the one with `start.bat` in it, e.g. `C:\FraudDetection`.

## 2. Start the app

Double-click **`start.bat`** in the app folder. If Windows shows **"Windows protected your PC"**, click **More info**, then **Run anyway**.
The first time, it sets the app up (1-2 minutes, needs internet once).
Your browser then opens **http://127.0.0.1:5000**. If the page does not load at once, refresh it.
Keep the black window open while you use the app; close it to stop the app.
The window shows a "development server" warning - that is expected for this pilot and safe to ignore.

## 3. Import a file

On the start page, choose your file and click **Import**. The file name must end in `.csv` or `.xml`.

- **pain.001 XML** (versions 001.001.03 and 001.001.09), as exported by your payment system.
  Due date = requested execution date (`ReqdExctnDt`), created date = file creation time (`CreDtTm`).
  Transactions without a creditor account or with an "equivalent amount" (`EqvtAmt`) are rejected.
- **CSV**, saved as UTF-8, comma-separated, `.` as decimal separator, no thousands separators. First line, exactly:
  ```
  transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date
  T1001,1234.56.78903,9876.54.32109,2500.00,NOK,2026-11-15,2026-10-20
  ```
  `created_date` may be left empty. Note: Excel with Norwegian or Swedish settings saves `;` and `,` decimals - such files are rejected.

After the upload you see a summary: **imported**, **flagged**, **duplicates** (a transaction ID that was already imported, also earlier in the same file, is skipped) and **errors** (the line or transaction and the reason). Fix the rows with errors and upload the file again - rows imported before are skipped automatically.
The **Transactions** link at the top shows everything imported so far, with the flags of each transaction.

## 4. What the flags mean

| Flag | Meaning |
|---|---|
| HIGH_AMOUNT | Amount is above the limit for its currency: NOK 10 000, SEK 10 000, EUR 1 000 (exactly the limit is not flagged) |
| NEW_CREDITOR | This paying account has paid before, but never to this receiving account |
| FAR_FUTURE_DUE | Due date is more than 3 months after the transaction was created (or imported, if no created date) |
| PAST_DUE_DATE | Due date is before the transaction was created (or imported) |
| UNSUPPORTED_CURRENCY | Currency is not NOK, SEK or EUR; it has no amount limit, so check the amount manually |

A flag means **"check this"**, not "this is fraud". Before the payment is sent, confirm it with the person who requested it, using contact details you already have, not the ones on the invoice. The app never blocks or changes a payment.

## 5. Your data and security

- **Stays on your PC.** Transactions are stored only in the file `fraud_detection.db` in the app folder.
- **Nothing is sent anywhere.** The app makes no network connections and shares no data with us or anyone else.
- **Only reachable from your own PC.** The browser page answers only on `127.0.0.1`; other computers on your network cannot open it.
- **Not encrypted, no login.** Anyone who can use your Windows account can open the app and the data file. Protect it with a Windows password, and BitLocker disk encryption if your company uses it.
- **Backup:** stop the app, then copy `fraud_detection.db` to a safe place. To restore, copy it back.
- **Delete all data:** stop the app and delete `fraud_detection.db` (and any backups). When the pilot ends, delete the whole app folder.

## 6. Known limitations

- Windows PC, one user at a time; no user accounts.
- CSV and pain.001 only. JSON import is planned for a later release.
- NOK, SEK and EUR only; amounts are never converted between currencies.
- Duplicates are recognised by transaction ID only.
- Flags are rule-based and simple; they will not catch every fraud and will sometimes flag normal payments.

## 7. Feedback and problems

Contact your Autopay contact. For a problem, tell us what you did, what you expected and what happened, and include the file (with sensitive data removed) and a screenshot of the summary.
