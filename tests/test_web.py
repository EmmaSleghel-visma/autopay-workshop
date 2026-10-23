import io
import re
from pathlib import Path

from fraud_detection.web import create_app

PAIN001_SAMPLE = Path(__file__).parent.parent / "samples" / "pain001_v03.xml"
HEADER = "transaction_id,debtor_account,creditor_account,amount,currency,due_date,created_date\n"
CSV = (
    HEADER
    + "t1,D1,C1,500.00,NOK,2026-11-15,2026-10-20\n"
    + "t2,D1,C1,25000.00,NOK,2026-11-15,2026-10-20\n"
    + "t1,D1,C1,500.00,NOK,2026-11-15,2026-10-20\n"  # duplicate
    + "t3,D1,C1,abc,NOK,2026-11-15,2026-10-20\n"  # bad amount, line 5
)


def client(tmp_path):
    return create_app(str(tmp_path / "fraud.db")).test_client()


def upload(c, content, filename):
    data = {"file": (io.BytesIO(content), filename)}
    return c.post("/upload", data=data, content_type="multipart/form-data")


def test_app_starts_and_reports_health(tmp_path):
    response = client(tmp_path).get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_start_page_has_the_upload_form(tmp_path):
    html = client(tmp_path).get("/").get_data(as_text=True)
    assert 'enctype="multipart/form-data"' in html
    assert 'type="file"' in html and 'name="file"' in html


def test_csv_upload_shows_the_import_summary(tmp_path):
    response = upload(client(tmp_path), CSV.encode(), "transactions.csv")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Imported: 2" in html
    assert "Flagged: 1" in html
    assert "Duplicates: 1" in html and "t1" in html
    assert "Errors: 1" in html
    assert "Line 5:" in html


def test_xml_upload_uses_the_pain001_importer(tmp_path):
    html = upload(client(tmp_path), PAIN001_SAMPLE.read_bytes(), "export.xml").get_data(as_text=True)
    assert "Imported: 4" in html
    assert "Flagged: 3" in html


def test_errors_without_a_line_number_show_only_the_message(tmp_path):
    html = upload(client(tmp_path), b"<not-xml", "export.xml").get_data(as_text=True)
    assert "Errors: 1" in html
    assert "not valid XML" in html
    assert "Line 0" not in html


def test_non_utf8_file_is_reported_as_an_error(tmp_path):
    content = HEADER.encode() + b"t1,D1,C1,5.00,NOK,2026-11-15,\xe6\xf8\n"
    html = upload(client(tmp_path), content, "ansi.csv").get_data(as_text=True)
    assert "Errors: 1" in html
    assert "not UTF-8" in html


def test_upload_without_a_file_shows_an_error(tmp_path):
    response = client(tmp_path).post("/upload", data={}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "Choose a file" in response.get_data(as_text=True)


def test_transactions_page_lists_every_transaction_with_its_flags(tmp_path):
    c = client(tmp_path)
    upload(c, CSV.encode(), "transactions.csv")
    html = c.get("/transactions").get_data(as_text=True)
    assert "t1" in html and "t2" in html
    assert "HIGH_AMOUNT" in html
    assert html.count('class="flagged"') == 1


def many_rows(n):
    return HEADER + "".join(f"t{i},D1,C1,5.00,NOK,2026-11-15,2026-10-20\n" for i in range(1, n + 1))


def ids_on(html):
    return set(re.findall(r"<td>(t\d+)</td>", html))


def test_transactions_are_paged_newest_first(tmp_path):
    c = client(tmp_path)
    upload(c, many_rows(105).encode(), "many.csv")

    first = c.get("/transactions").get_data(as_text=True)
    assert ids_on(first) == {f"t{i}" for i in range(6, 106)}
    assert first.index("<td>t105</td>") < first.index("<td>t6</td>")
    assert "Showing 1–100 of 105" in first
    assert 'href="/transactions?page=2"' in first and "page=0" not in first

    second = c.get("/transactions?page=2").get_data(as_text=True)
    assert ids_on(second) == {f"t{i}" for i in range(1, 6)}
    assert "Showing 101–105 of 105" in second
    assert 'href="/transactions?page=1"' in second and "page=3" not in second


def test_out_of_range_or_invalid_page_numbers_are_clamped(tmp_path):
    c = client(tmp_path)
    upload(c, many_rows(105).encode(), "many.csv")
    assert "Showing 101–105 of 105" in c.get("/transactions?page=99").get_data(as_text=True)
    assert "Showing 1–100 of 105" in c.get("/transactions?page=abc").get_data(as_text=True)
    assert "Showing 1–100 of 105" in c.get("/transactions?page=-3").get_data(as_text=True)


def test_flags_are_explained_in_plain_language(tmp_path):
    c = client(tmp_path)
    csv = (
        HEADER
        + "a,D1,C1,20000.00,SEK,2026-11-15,2026-10-20\n"
        + "b,D1,C2,5.00,NOK,2027-03-01,2026-10-20\n"
        + "c,D2,C1,5.00,USD,2026-10-01,2026-10-20\n"
    )
    upload(c, csv.encode(), "reasons.csv")
    html = c.get("/transactions").get_data(as_text=True)
    assert "Amount above SEK 10 000" in html
    assert "First payment from this debtor to this creditor" in html
    assert "Due date more than 3 months after the created date" in html
    assert "Due date before the created date" in html
    assert "Currency USD is not supported (only NOK, SEK and EUR)" in html
    assert "HIGH_AMOUNT" in html  # the code stays visible next to the explanation


def test_reasons_refer_to_the_import_date_when_there_is_no_created_date(tmp_path):
    c = client(tmp_path)
    upload(c, (HEADER + "a,D1,C1,5.00,NOK,2000-01-01,\n").encode(), "old.csv")
    assert "Due date before the import date" in c.get("/transactions").get_data(as_text=True)


def test_upload_works_when_the_upload_stream_has_no_readable(tmp_path, monkeypatch):
    # Simulates Python 3.10, where SpooledTemporaryFile has no readable()/seekable().
    import tempfile

    monkeypatch.delattr(tempfile.SpooledTemporaryFile, "readable", raising=False)
    monkeypatch.delattr(tempfile.SpooledTemporaryFile, "seekable", raising=False)
    big = HEADER + "".join(f"s{i},D1,C1,5.00,NOK,2026-11-15,2026-10-20\n" for i in range(20000))  # > 500 KB, so spooled
    response = upload(client(tmp_path), big.encode(), "big.csv")
    assert response.status_code == 200
    assert "Imported: 20000" in response.get_data(as_text=True)
