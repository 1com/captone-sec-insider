import pyarrow as pa

from sentinel.ingest.sec_tables import read_table


def test_literal_quotes_do_not_merge_rows(tmp_path, quarter_zip):
    rows = [
        {"ACCESSION_NUMBER": "a1", "FOOTNOTE_ID": "F1", "FOOTNOTE_TXT": 'He said "buy'},
        {"ACCESSION_NUMBER": "a1", "FOOTNOTE_ID": "F2", "FOOTNOTE_TXT": 'a 10b5-1 "plan"'},
        {"ACCESSION_NUMBER": "a2", "FOOTNOTE_ID": "F1", "FOOTNOTE_TXT": 'end"'},
    ]
    z = tmp_path / "q.zip"
    z.write_bytes(quarter_zip({"FOOTNOTES": rows}))
    t = read_table(z, "FOOTNOTES")
    assert t.num_rows == 3
    assert t.column("FOOTNOTE_TXT").to_pylist() == ['He said "buy', 'a 10b5-1 "plan"', 'end"']


def test_every_column_is_text(tmp_path, quarter_zip):
    z = tmp_path / "q.zip"
    z.write_bytes(
        quarter_zip({"NONDERIV_TRANS": [{"ACCESSION_NUMBER": "a", "TRANS_SHARES": "100"}]})
    )
    t = read_table(z, "NONDERIV_TRANS")
    assert all(f.type == pa.string() for f in t.schema)


def test_missing_requested_column_is_all_null(tmp_path, quarter_zip):
    z = tmp_path / "q.zip"
    z.write_bytes(quarter_zip({"SUBMISSION": [{"ACCESSION_NUMBER": "a"}]}))
    t = read_table(z, "SUBMISSION", columns=["ACCESSION_NUMBER", "AFF10B5ONE"])
    assert t.column_names == ["ACCESSION_NUMBER", "AFF10B5ONE"]
    assert t.column("AFF10B5ONE").to_pylist() == [None]


def test_projection_returns_only_requested_columns(tmp_path, quarter_zip):
    z = tmp_path / "q.zip"
    z.write_bytes(
        quarter_zip({"SUBMISSION": [{"ACCESSION_NUMBER": "a", "ISSUERCIK": "1"}]}, checkbox=True)
    )
    t = read_table(z, "SUBMISSION", columns=["ISSUERCIK", "AFF10B5ONE"])
    assert t.column_names == ["ISSUERCIK", "AFF10B5ONE"]
    assert t.column("ISSUERCIK").to_pylist() == ["1"]
