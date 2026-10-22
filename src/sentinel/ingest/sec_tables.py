"""Read one table out of a quarterly SEC archive, streaming, with every column as text.

The files are tab-separated UTF-8 with literal `"` characters inside fields, so quoting must be off
(research.md R2). Columns absent from older files (e.g. AFF10B5ONE before 2023) can be requested
and come back as all-null.
"""

import io
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv


def read_table(zip_path: Path, table: str, columns: list[str] | None = None) -> pa.Table:
    member = f"{table}.tsv"
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member) as f:
            header = io.TextIOWrapper(f, encoding="utf-8", newline="").readline()
        names = header.rstrip("\r\n").split("\t")
        wanted = [c for c in (columns or names) if c in names]
        with zf.open(member) as f:
            data = pacsv.read_csv(
                f,
                read_options=pacsv.ReadOptions(encoding="utf8", block_size=16 << 20),
                parse_options=pacsv.ParseOptions(
                    delimiter="\t", quote_char=False, double_quote=False, escape_char=False
                ),
                convert_options=pacsv.ConvertOptions(
                    column_types={c: pa.string() for c in names},
                    include_columns=wanted,
                    strings_can_be_null=False,
                ),
            )
    if columns is None:
        return data
    arrays = [
        data.column(c) if c in names else pa.nulls(data.num_rows, pa.string()) for c in columns
    ]
    return pa.table(arrays, names=columns)
