"""Web layer: real upload form, summary and transactions pages through the Flask test client."""

import io
import json
import re
import time
from datetime import date
from html.parser import HTMLParser

import pytest

import fraud_detection.web as web
from fraud_detection.web import create_app
from qa_support import DATA_DIR, IMPORT_DATE, flag_mismatches

PAIN_DIR = DATA_DIR / "pain001"
HEADER = "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date\n"
SCRIPT = "<script>alert(1)</script>"
SCRIPT_ESCAPED = "&lt;script&gt;alert(1)&lt;/script&gt;"


class FixedDate(date):
    @classmethod
    def today(cls):
        return IMPORT_DATE


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tables, self.items, self.errors_shown = [], [], []
        self._row = self._cell = self._li = self._p_error = None
        self._section = ""
        self._h2 = None
        self._in_span = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self.tables.append([])
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = {"text": "", "spans": []}
        elif tag == "span" and self._cell is not None:
            self._in_span = True
            self._cell["spans"].append("")
        elif tag == "li":
            self._li = ""
        elif tag == "h2":
            self._h2 = ""
        elif tag == "p" and "error" in (attrs.get("class") or ""):
            self._p_error = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._cell["text"] = self._cell["text"].strip()
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None
        elif tag == "span":
            self._in_span = False
        elif tag == "li" and self._li is not None:
            self.items.append((self._section, self._li.strip()))
            self._li = None
        elif tag == "h2" and self._h2 is not None:
            self._section, self._h2 = self._h2.strip(), None
        elif tag == "p" and self._p_error is not None:
            self.errors_shown.append(self._p_error.strip())
            self._p_error = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data
            if self._in_span:
                self._cell["spans"][-1] += data
        if self._li is not None:
            self._li += data
        if self._h2 is not None:
            self._h2 += data
        if self._p_error is not None:
            self._p_error += data

    def counts(self):
        found = {}
        for section, text in self.items:
            m = re.fullmatch(r"(Imported|Flagged|Duplicates|Errors): (\d+)", text)
            if section == "" and m:
                found[m.group(1).lower()] = int(m.group(2))
        return found

    def section(self, name):
        return [text for section, text in self.items if section.startswith(name)]

    def transactions(self):
        if not self.tables:
            return {}
        header, *rows = self.tables[0]
        names = [c["text"] for c in header]
        id_col, rules_col = names.index("Transaction ID"), names.index("Rules triggered")
        return {r[id_col]["text"]: {"row": [c["text"] for c in r], "flags": [s.strip() for s in r[rules_col]["spans"]],
                                    "names": names} for r in rows}

    def transaction_ids(self):
        if not self.tables:
            return []
        names = [c["text"] for c in self.tables[0][0]]
        id_col = names.index("Transaction ID")
        return [r[id_col]["text"] for r in self.tables[0][1:]]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "date", FixedDate)
    app = create_app(str(tmp_path / "web.db"))
    yield app.test_client()
    app.config["STORE"].close()


def upload(client, content, filename):
    return client.post("/upload", data={"file": (io.BytesIO(content), filename)}, content_type="multipart/form-data")


def upload_file(client, path, filename=None):
    return upload(client, path.read_bytes(), filename or path.name)


def form_field_name(client):
    m = re.search(r'<input[^>]*type="file"[^>]*name="([^"]+)"', client.get("/").get_data(as_text=True))
    return m.group(1) if m else None


def upload_via_form(client, path):
    field = form_field_name(client)
    return client.post("/upload", data={field: (io.BytesIO(path.read_bytes()), path.name)},
                       content_type="multipart/form-data")


def summary_mismatch(label, page, want):
    got = page.counts()
    if got != want:
        return [f"{label}: expected summary {want}, page shows {got}"]
    return []


@pytest.fixture
def uploaded_all(client, expected):
    pages = {}
    for name in expected["import_order"]:
        response = upload_via_form(client, DATA_DIR / name)
        pages[name] = (response.status_code, Page(response.get_data(as_text=True)))
    return pages, Page(client.get("/transactions").get_data(as_text=True))


def category_mismatches(expected, uploaded_all, category):
    _, table = uploaded_all
    rows = table.transactions()
    return flag_mismatches(expected, category, {i: r["flags"] for i, r in rows.items()})


def test_upload_form_posts_a_file_field_to_upload(client):
    html = client.get("/").get_data(as_text=True)
    assert form_field_name(client) == "file"
    assert 'action="/upload"' in html and 'method="post"' in html and 'enctype="multipart/form-data"' in html


def test_summaries_match_expected(expected, uploaded_all):
    pages, _ = uploaded_all
    failures = []
    for name, (status, page) in pages.items():
        if status != 200:
            failures.append(f"{name}: HTTP {status}")
        failures += summary_mismatch(name, page, expected["summaries"][name])
    assert not failures, "\n".join(failures)


def test_duplicates_are_listed_on_the_summary(expected, uploaded_all):
    pages, _ = uploaded_all
    failures = []
    for e in expected["transactions"]:
        if e["status"] == "DUPLICATE" and e["transaction_id"] not in pages[e["file"]][1].section("Duplicates"):
            failures.append(f"{e['case']} {e['transaction_id']}: not listed under Duplicates on the {e['file']} summary")
    assert not failures, "\n".join(failures)


def test_error_rows_show_their_line_numbers(expected, uploaded_all):
    pages, _ = uploaded_all
    failures = []
    for name in expected["import_order"]:
        lines = (DATA_DIR / name).read_text(encoding="utf-8-sig").splitlines()
        shown = pages[name][1].section("Errors")
        for e in expected["transactions"]:
            if e["file"] != name or e["status"] != "ERROR":
                continue
            if not e["transaction_id"]:
                continue
            numbers = [i + 1 for i, line in enumerate(lines) if line.split(",")[0].strip('"') == e["transaction_id"]]
            if not numbers:
                failures.append(f"{e['case']} {e['transaction_id']}: row not found in {name}")
            elif not any(text.startswith(f"Line {numbers[0]}: ") for text in shown):
                failures.append(f"{e['case']} {e['transaction_id']}: no 'Line {numbers[0]}:' error on the summary, got {shown}")
        if len(shown) != expected["summaries"][name]["errors"] or not all(re.match(r"Line \d+: \S", t) for t in shown):
            failures.append(f"{name}: expected {expected['summaries'][name]['errors']} 'Line N: message' errors, got {shown}")
    assert not failures, "\n".join(failures)


def test_transactions_page_lists_every_imported_id_once(expected, uploaded_all):
    _, table = uploaded_all
    ids = table.transaction_ids()
    want = {e["transaction_id"] for e in expected["transactions"] if e["status"] == "IMPORTED"}
    failures = []
    if sorted(set(ids)) != sorted(ids):
        failures.append(f"ids listed more than once: {sorted(i for i in set(ids) if ids.count(i) > 1)}")
    if set(ids) - want:
        failures.append(f"listed but not expected as imported: {sorted(set(ids) - want)}")
    if want - set(ids):
        failures.append(f"expected as imported but not listed: {sorted(want - set(ids))}")
    assert not failures, "\n".join(failures)


def test_transactions_page_flags_positive_cases(expected, uploaded_all):
    failures = category_mismatches(expected, uploaded_all, "POS")
    assert not failures, "\n".join(failures)


def test_transactions_page_flags_negative_cases(expected, uploaded_all):
    failures = category_mismatches(expected, uploaded_all, "NEG")
    assert not failures, "\n".join(failures)


def test_transactions_page_flags_corner_cases(expected, uploaded_all):
    failures = category_mismatches(expected, uploaded_all, "CORNER")
    assert not failures, "\n".join(failures)


def test_flagged_rows_are_marked_flagged(uploaded_all):
    _, table = uploaded_all
    failures = []
    for tx_id, r in table.transactions().items():
        status = r["row"][r["names"].index("Status")]
        if status != ("Flagged" if r["flags"] else "OK"):
            failures.append(f"{tx_id}: status '{status}' with flags {r['flags']}")
    assert not failures, "\n".join(failures)


def test_web_csv_files_give_expected_imported_and_errors(expected, tmp_path, monkeypatch):
    monkeypatch.setattr(web, "date", FixedDate)
    failures = []
    for f in expected["files"]:
        if f["case"] == "FILE-12":
            continue
        app = create_app(str(tmp_path / f"{f['case']}.db"))
        try:
            response = upload_file(app.test_client(), DATA_DIR / f["file"])
            got = Page(response.get_data(as_text=True)).counts()
            if response.status_code >= 500:
                failures.append(f"{f['case']} {f['file']}: HTTP {response.status_code}")
            elif (got.get("imported"), got.get("errors")) != (f["imported"], f["errors"]):
                failures.append(f"{f['case']} {f['file']}: expected imported/errors {(f['imported'], f['errors'])}, "
                                f"page shows {got} ({f['expect']})")
        finally:
            app.config["STORE"].close()
    assert not failures, "\n".join(failures)


def test_web_pain001_files_give_expected_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "date", FixedDate)
    steps = json.loads((PAIN_DIR / "expected_pain001.json").read_text(encoding="utf-8"))["steps"]
    by_case = {s["case"]: s for s in steps}
    failures = []
    for group in (["FILE-P01", "FILE-P02"], ["FILE-01"], ["FILE-08"], ["FILE-09"], ["FILE-10"], ["FILE-12"]):
        app = create_app(str(tmp_path / f"{group[0]}.db"))
        try:
            c = app.test_client()
            for case in group:
                step = by_case[case]
                response = upload_file(c, PAIN_DIR / step["file"])
                page = Page(response.get_data(as_text=True))
                if response.status_code >= 500:
                    failures.append(f"{case} {step['file']}: HTTP {response.status_code}")
                    continue
                failures += summary_mismatch(f"{case} {step['file']}", page, step["summary"])
                if step["file_error"] and not any(step["file_error"] in t for t in page.section("Errors")):
                    failures.append(f"{case} {step['file']}: error '{step['file_error']}' not shown, got {page.section('Errors')}")
        finally:
            app.config["STORE"].close()
    assert not failures, "\n".join(failures)


def test_no_file_selected_shows_a_clear_message(client):
    failures = []
    for label, data in (("no file field", {}), ("empty filename", {"file": (io.BytesIO(b""), "")})):
        response = client.post("/upload", data=data, content_type="multipart/form-data")
        page = Page(response.get_data(as_text=True))
        if response.status_code != 400 or not any("Choose a file" in t for t in page.errors_shown):
            failures.append(f"{label}: HTTP {response.status_code}, errors shown {page.errors_shown}")
    assert not failures, "\n".join(failures)


def test_unsupported_and_huge_uploads_do_not_crash(client):
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 4
    huge = b"x" * (20 * 1024 * 1024)
    failures = []
    for label, content, filename in (("png", png, "logo.png"), ("binary txt", (DATA_DIR / "file_not_csv.txt").read_bytes(), "notes.txt"),
                                     ("20 MB", huge, "huge.csv")):
        response = upload(client, content, filename)
        page = Page(response.get_data(as_text=True))
        if response.status_code >= 500:
            failures.append(f"{label}: HTTP {response.status_code}")
        elif response.status_code == 200 and (page.counts().get("imported") != 0 or not page.section("Errors")):
            failures.append(f"{label}: expected 0 imported and an error message, got {page.counts()} {page.section('Errors')}")
    assert client.get("/transactions").status_code == 200
    assert not failures, "\n".join(failures)


def test_html_in_debtor_id_and_filename_is_escaped_everywhere(client):
    html_id = "<b>bold-id</b>"
    csv = HEADER + f"{html_id},5000.11.55555,9000.11.00001,100.00,NOK,2026-11-01,2026-10-01\n"
    csv += f"T-XSS-W,{SCRIPT},9000.11.00001,100.00,NOK,2026-11-01,2026-10-01\n"
    failures = []
    pages = {
        "first summary": upload(client, csv.encode(), f"{SCRIPT}.csv").get_data(as_text=True),
        "duplicate summary": upload(client, csv.encode(), f"{SCRIPT}.csv").get_data(as_text=True),
        "transactions": client.get("/transactions").get_data(as_text=True),
    }
    for label, html in pages.items():
        if SCRIPT in html or html_id in html:
            failures.append(f"{label}: raw HTML from the upload rendered unescaped")
    if SCRIPT_ESCAPED not in pages["first summary"]:
        failures.append("first summary: escaped filename not shown")
    if "&lt;b&gt;bold-id&lt;/b&gt;" not in pages["duplicate summary"]:
        failures.append("duplicate summary: escaped transaction id not listed")
    if SCRIPT_ESCAPED not in pages["transactions"] or "&lt;b&gt;bold-id&lt;/b&gt;" not in pages["transactions"]:
        failures.append("transactions: escaped debtor or transaction id not shown")
    assert not failures, "\n".join(failures)


def test_xss_row_from_all_rules_is_escaped(client):
    upload_file(client, DATA_DIR / "all_rules.csv")
    html = client.get("/transactions").get_data(as_text=True)
    assert SCRIPT not in html
    assert SCRIPT_ESCAPED in html


def test_same_file_twice_second_summary_is_all_duplicates(client, expected):
    path = DATA_DIR / "all_rules.csv"
    upload_via_form(client, path)
    second = Page(upload_via_form(client, path).get_data(as_text=True))
    first = expected["summaries"]["all_rules.csv"]
    want = {"imported": 0, "flagged": 0, "duplicates": first["imported"] + first["duplicates"], "errors": first["errors"]}
    failures = summary_mismatch("second upload", second, want)
    ids = Page(client.get("/transactions").get_data(as_text=True)).transaction_ids()
    if len(ids) != len(set(ids)) or len(ids) != first["imported"]:
        failures.append(f"transactions page: {len(ids)} rows, {len(set(ids))} unique, expected {first['imported']}")
    assert not failures, "\n".join(failures)


def test_refresh_resubmit_does_not_store_twice(client):
    csv = (HEADER + "R-1,5000.11.55555,9000.11.00001,100.00,NOK,2026-11-01,2026-10-01\n").encode()
    first = upload(client, csv, "refresh.csv")
    resubmit = upload(client, csv, "refresh.csv")
    failures = []
    if first.status_code == 200 and "Import summary" in first.get_data(as_text=True):
        print("FINDING: POST /upload renders the summary directly (no POST-redirect-GET); a browser refresh re-POSTs the file")
    if Page(resubmit.get_data(as_text=True)).counts() != {"imported": 0, "flagged": 0, "duplicates": 1, "errors": 0}:
        failures.append(f"re-POST summary: {Page(resubmit.get_data(as_text=True)).counts()}")
    ids = Page(client.get("/transactions").get_data(as_text=True)).transaction_ids()
    if ids != ["R-1"]:
        failures.append(f"transactions after re-POST: {ids}")
    assert not failures, "\n".join(failures)


def test_wrong_methods_and_unknown_route(client):
    failures = []
    for method, url in (("get", "/upload"), ("post", "/"), ("post", "/transactions"), ("put", "/upload"),
                        ("delete", "/transactions"), ("post", "/health")):
        status = getattr(client, method)(url).status_code
        if status != 405:
            failures.append(f"{method.upper()} {url}: expected 405, got {status}")
    status = client.get("/no-such-page").status_code
    if status != 404:
        failures.append(f"GET /no-such-page: expected 404, got {status}")
    assert not failures, "\n".join(failures)


@pytest.mark.slow
def test_transactions_page_with_10k_rows(client):
    start = time.perf_counter()
    summary = Page(upload_file(client, DATA_DIR / "file_large_10k.csv").get_data(as_text=True)).counts()
    upload_seconds = time.perf_counter() - start
    start = time.perf_counter()
    response = client.get("/transactions")
    render_seconds = time.perf_counter() - start
    html = response.get_data(as_text=True)
    rows = len(Page(html).transaction_ids())
    paginated = bool(re.search(r"page=|[Nn]ext|[Pp]revious|[Pp]age \d", html))
    print(f"10k: upload {upload_seconds:.2f}s, /transactions {render_seconds:.2f}s, {len(html) / 1e6:.1f} MB HTML, "
          f"{rows} rows on one page, pagination={'yes' if paginated else 'no'}")
    failures = []
    if summary.get("imported") != 10000:
        failures.append(f"10k upload summary: {summary}")
    if response.status_code != 200 or rows != 10000 and not paginated:
        failures.append(f"/transactions: HTTP {response.status_code}, {rows} rows, pagination={paginated}")
    if render_seconds > 5:
        failures.append(f"/transactions took {render_seconds:.2f}s to render 10k rows (budget 5 s)")
    assert not failures, "\n".join(failures)
