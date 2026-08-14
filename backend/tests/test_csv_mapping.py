"""CSV reading, intelligent column mapping and data preservation (spec 2, 46)."""

from __future__ import annotations

import csv as csvmod

import pytest

from app.core.csv_mapping import (
    CsvReadError,
    count_rows,
    excel_to_csv_text,
    preview_csv,
    read_csv,
    suggest_mapping,
)


def write_csv(path, headers, rows, delimiter=",", encoding="utf-8", newline=""):
    with open(path, "w", encoding=encoding, newline=newline) as fh:
        w = csvmod.writer(fh, delimiter=delimiter)
        w.writerow(headers)
        w.writerows(rows)
    return path


class TestMappingDetection:
    def test_google_maps_style_headers(self, tmp_path):
        headers = ["Business Name", "Category", "Phone Number", "Website URL",
                   "Full Address", "City", "State", "Country", "Zip", "Rating",
                   "Reviews", "Place ID", "Google Maps Link"]
        rows = [["Brightwater Plumbing", "Plumber", "+44 113 296 0001",
                 "https://brightwaterplumbing.co.uk", "14 Kirkstall Road", "Leeds",
                 "", "United Kingdom", "LS1 4AB", "4.8", "210", "ChIJabc",
                 "https://maps.google.com/?cid=1"]]
        p = write_csv(tmp_path / "a.csv", headers, rows)
        result = preview_csv(p)
        m = result["mapping"]
        assert m["business_name"] == "Business Name"
        assert m["phone"] == "Phone Number"
        assert m["website"] == "Website URL"
        assert m["city"] == "City"
        assert m["postal_code"] == "Zip"
        assert m["rating"] == "Rating"
        assert m["review_count"] == "Reviews"
        assert m["google_maps_url"] == "Google Maps Link"

    def test_snake_case_headers(self, tmp_path):
        headers = ["business_name", "phone", "website", "city", "review_count"]
        rows = [["Acme Ltd", "+12025550143", "acme.com", "Austin", "12"]]
        p = write_csv(tmp_path / "b.csv", headers, rows)
        m = preview_csv(p)["mapping"]
        assert m["business_name"] == "business_name"
        assert m["review_count"] == "review_count"

    def test_unconventional_headers_are_matched_by_value_shape(self, tmp_path):
        headers = ["col_a", "col_b", "col_c"]
        rows = [
            ["Acme Plumbing", "+1 202-555-0143", "https://acmeplumbing.com"],
            ["Bee Dental", "+1 202-555-0144", "https://beedental.com"],
            ["Cee Roofing", "+1 202-555-0145", "https://ceeroofing.com"],
        ]
        p = write_csv(tmp_path / "c.csv", headers, rows)
        m = preview_csv(p)["mapping"]
        assert m["phone"] == "col_b"
        assert m["website"] == "col_c"

    def test_ambiguous_file_is_flagged_for_review(self, tmp_path):
        headers = ["x1", "x2"]
        rows = [["foo", "bar"], ["baz", "qux"]]
        p = write_csv(tmp_path / "d.csv", headers, rows)
        result = preview_csv(p)
        assert result["needs_review"] is True
        assert "business_name" in result["missing_required"]

    def test_one_column_is_never_claimed_by_two_fields(self, tmp_path):
        headers = ["name", "company name", "phone"]
        rows = [["Dave", "Brightwater Plumbing", "+441132960001"]]
        p = write_csv(tmp_path / "e.csv", headers, rows)
        m = preview_csv(p)["mapping"]
        assigned = [c for c in m.values() if c]
        assert len(assigned) == len(set(assigned))

    def test_similar_but_wrong_headers_are_not_mismatched(self):
        headers = ["business name", "review_url", "email_status"]
        rows = [{"business name": "X", "review_url": "https://g.co/r",
                 "email_status": "verified"}]
        m = suggest_mapping(headers, rows)["mapping"]
        assert m["review_count"] != "review_url"
        assert m["email"] != "email_status"

    def test_confidence_is_reported(self, tmp_path):
        headers = ["Business Name", "Phone"]
        rows = [["Acme", "+12025550143"]]
        p = write_csv(tmp_path / "f.csv", headers, rows)
        result = preview_csv(p)
        assert 0 < result["confidence"]["business_name"] <= 1.0


class TestReading:
    def test_all_original_columns_are_preserved(self, tmp_path):
        headers = ["Business Name", "Weird Custom Column", "Another One", "Phone"]
        rows = [["Acme", "keep me", "and me", "+12025550143"]]
        p = write_csv(tmp_path / "g.csv", headers, rows)
        got_headers, got_rows = read_csv(p)
        assert got_headers == headers
        assert got_rows[0]["Weird Custom Column"] == "keep me"
        assert got_rows[0]["Another One"] == "and me"

    def test_semicolon_delimiter_detected(self, tmp_path):
        p = write_csv(tmp_path / "h.csv", ["name", "phone"],
                      [["Acme", "+12025550143"]], delimiter=";")
        headers, rows = read_csv(p)
        assert headers == ["name", "phone"]
        assert rows[0]["phone"] == "+12025550143"

    def test_tab_delimiter_detected(self, tmp_path):
        p = write_csv(tmp_path / "i.csv", ["name", "phone"],
                      [["Acme", "+12025550143"]], delimiter="\t")
        headers, _ = read_csv(p)
        assert headers == ["name", "phone"]

    def test_utf8_bom_is_handled(self, tmp_path):
        p = write_csv(tmp_path / "j.csv", ["Business Name", "City"],
                      [["Café Noir", "Montréal"]], encoding="utf-8-sig")
        headers, rows = read_csv(p)
        assert headers[0] == "Business Name"
        assert rows[0]["Business Name"] == "Café Noir"

    def test_duplicate_headers_are_disambiguated(self, tmp_path):
        path = tmp_path / "k.csv"
        path.write_text("name,name,phone\nA,B,+12025550143\n", encoding="utf-8")
        headers, rows = read_csv(path)
        assert len(set(headers)) == 3
        assert rows[0][headers[0]] == "A"
        assert rows[0][headers[1]] == "B"

    def test_short_rows_are_padded_not_dropped(self, tmp_path):
        path = tmp_path / "l.csv"
        path.write_text("name,phone,city\nAcme,+12025550143\n", encoding="utf-8")
        headers, rows = read_csv(path)
        assert len(rows) == 1
        assert rows[0]["city"] == ""

    def test_overflow_cells_are_kept_not_discarded(self, tmp_path):
        path = tmp_path / "m.csv"
        path.write_text("name,phone\nAcme,+12025550143,extra-value\n", encoding="utf-8")
        headers, rows = read_csv(path)
        assert "extra-value" in rows[0].get("_extra_columns", "")

    def test_blank_lines_are_skipped(self, tmp_path):
        path = tmp_path / "n.csv"
        path.write_text("name,phone\nAcme,+12025550143\n\n\nBee,+12025550144\n", encoding="utf-8")
        _, rows = read_csv(path)
        assert len(rows) == 2

    def test_row_count_matches(self, tmp_path):
        rows = [[f"Business {i}", f"+120255501{i:02d}"] for i in range(20)]
        p = write_csv(tmp_path / "o.csv", ["name", "phone"], rows)
        assert count_rows(p) == 20
        _, got = read_csv(p)
        assert len(got) == 20

    def test_limit_is_respected(self, tmp_path):
        rows = [[f"B{i}", "+12025550143"] for i in range(50)]
        p = write_csv(tmp_path / "p.csv", ["name", "phone"], rows)
        _, got = read_csv(p, limit=10)
        assert len(got) == 10

    def test_empty_file_raises_clear_error(self, tmp_path):
        path = tmp_path / "q.csv"
        path.write_text("", encoding="utf-8")
        with pytest.raises(CsvReadError):
            read_csv(path)

    def test_header_only_file_raises_clear_error(self, tmp_path):
        path = tmp_path / "r.csv"
        path.write_text("name,phone\n", encoding="utf-8")
        with pytest.raises(CsvReadError):
            read_csv(path)

    def test_quoted_commas_survive(self, tmp_path):
        p = write_csv(tmp_path / "s.csv", ["name", "address"],
                      [["Acme, Inc", "14 Kirkstall Road, Leeds, LS1 4AB"]])
        _, rows = read_csv(p)
        assert rows[0]["address"] == "14 Kirkstall Road, Leeds, LS1 4AB"
        assert rows[0]["name"] == "Acme, Inc"


class TestExcelIngestion:
    """Excel is converted to CSV text once, at the door, so read_csv/suggest_mapping
    are exercised identically for both formats - nothing downstream is duplicated."""

    def _workbook_bytes(self, rows):
        import io as iomod

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        buf = iomod.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_excel_round_trips_through_read_csv(self, tmp_path):
        raw = self._workbook_bytes([
            ["Business Name", "Phone", "Rating"],
            ["Acme Plumbing", "+12025550143", 4.5],
            ["Bee Dental", "+12025550144", 5],
        ])
        text = excel_to_csv_text(raw)
        p = tmp_path / "converted.csv"
        p.write_text(text, encoding="utf-8")
        headers, rows = read_csv(p)
        assert headers == ["Business Name", "Phone", "Rating"]
        assert rows[0]["Business Name"] == "Acme Plumbing"
        # Whole-number floats (Excel stores 5 as 5.0) come out as plain integers.
        assert rows[1]["Rating"] == "5"
        assert rows[0]["Rating"] == "4.5"

    def test_excel_feeds_the_same_mapping_as_csv(self, tmp_path):
        raw = self._workbook_bytes([
            ["Business Name", "Phone Number", "Website URL", "City"],
            ["Excel Co", "+44 113 296 0001", "https://excel-co.invalid", "Leeds"],
        ])
        text = excel_to_csv_text(raw)
        p = tmp_path / "from_excel.csv"
        p.write_text(text, encoding="utf-8")
        result = preview_csv(p)
        assert result["mapping"]["business_name"] == "Business Name"
        assert result["mapping"]["phone"] == "Phone Number"
        assert result["mapping"]["website"] == "Website URL"

    def test_blank_rows_are_skipped(self, tmp_path):
        raw = self._workbook_bytes([
            ["name", "phone"],
            ["Acme", "+12025550143"],
            [None, None],
            ["Bee", "+12025550144"],
        ])
        text = excel_to_csv_text(raw)
        p = tmp_path / "blanks.csv"
        p.write_text(text, encoding="utf-8")
        _, rows = read_csv(p)
        assert len(rows) == 2

    def test_empty_workbook_raises_clear_error(self):
        raw = self._workbook_bytes([])
        with pytest.raises(CsvReadError):
            excel_to_csv_text(raw)

    def test_corrupt_file_raises_clear_error(self):
        with pytest.raises(CsvReadError):
            excel_to_csv_text(b"not a real xlsx file")
