"""End-user journeys in a real Chromium browser against the app served on a free local port."""

import csv
import threading
from datetime import date

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

import fraud_detection.web as web
from fraud_detection.web import create_app
from qa_support import DATA_DIR, IMPORT_DATE

pytestmark = pytest.mark.slow


class FixedDate(date):
    @classmethod
    def today(cls):
        return IMPORT_DATE


@pytest.fixture
def base_url(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "date", FixedDate)
    app = create_app(str(tmp_path / "browser.db"))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=10)
    app.config["STORE"].close()


@pytest.fixture
def page(base_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(base_url=base_url)
        pg.set_default_timeout(15000)
        yield pg
        browser.close()


def upload(page, path):
    page.goto("/")
    page.locator("input[type=file]").set_input_files(str(path))
    page.get_by_role("button", name="Import").click()
    page.wait_for_load_state()


def counts(page):
    return {t.split(":")[0].strip().lower(): int(t.split(":")[1]) for t in page.locator("ul.counts li").all_inner_texts()}


def rules_on_page(page, transaction_id):
    row = page.locator("tbody tr").filter(has=page.get_by_role("cell", name=transaction_id, exact=True))
    if row.count() != 1:
        return None
    return sorted(row.locator("span.rule").all_inner_texts())


def test_user_uploads_a_csv_and_reads_the_summary(page, expected):
    upload(page, DATA_DIR / "all_rules.csv")
    assert page.get_by_role("heading", name="Import summary").is_visible()
    assert page.get_by_text("File: all_rules.csv").is_visible()
    assert counts(page) == expected["summaries"]["all_rules.csv"]


def test_user_finds_a_flagged_row_in_the_transactions_table(page, expected):
    upload(page, DATA_DIR / "all_rules.csv")
    page.get_by_role("link", name="View all transactions").click()
    page.wait_for_load_state()
    assert page.get_by_role("heading", name="All transactions").is_visible()
    flagged = next(e for e in expected["transactions"]
                   if e["file"] == "all_rules.csv" and e["status"] == "IMPORTED" and e["flags"])
    row = page.locator("tbody tr").filter(has=page.get_by_role("cell", name=flagged["transaction_id"], exact=True))
    assert row.count() == 1
    assert "flagged" in (row.get_attribute("class") or "")
    assert row.get_by_role("cell", name="Flagged", exact=True).is_visible()
    assert sorted(row.locator("span.rule").all_inner_texts()) == flagged["flags"]


def test_user_uploads_a_bad_file_and_reads_the_error(page):
    upload(page, DATA_DIR / "file_bad_header.csv")
    assert counts(page)["imported"] == 0
    error = page.locator("ul.error li").first
    assert error.is_visible()
    assert error.inner_text().startswith("Line 1:")
    assert "missing column" in error.inner_text()


def test_user_sees_correct_flags_on_sek_and_eur_rows(page, expected):
    with open(DATA_DIR / "all_rules.csv", newline="", encoding="utf-8-sig") as f:
        currency = {r["transaction_id"]: r["currency"].strip().upper() for r in csv.DictReader(f)}
    cases = [e for e in expected["transactions"] if e["file"] == "all_rules.csv" and e["status"] == "IMPORTED"
             and currency.get(e["transaction_id"]) in ("SEK", "EUR")]
    upload(page, DATA_DIR / "all_rules.csv")
    page.goto("/transactions")
    failures = []
    for e in cases:
        got = rules_on_page(page, e["transaction_id"])
        if got != e["flags"]:
            failures.append(f"{e['case']} {e['transaction_id']} {currency[e['transaction_id']]}: "
                            f"expected {e['flags'] or 'no flags'}, page shows {got} ({e['note']})")
    assert cases, "no SEK/EUR rows found in all_rules.csv"
    assert not failures, "\n".join(failures)
