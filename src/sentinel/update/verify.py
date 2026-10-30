"""`sentinel verify`: rebuild every layer from the stored files into a scratch database
(`data/verify.duckdb`) and compare each table with the build database by row count and checksum
(spec FR-015, SC-005: the daily update must equal a full rebuild). Takes as long as a full build;
run it the same day as the update it checks."""

import dataclasses

import duckdb

from sentinel import build, db
from sentinel.config import Paths
from sentinel.update import record

LAYERS = ("staging", "reference", "core", "features", "labels")


def verify(p: Paths, keep: bool = False, echo=print, layers=LAYERS) -> list[str]:
    """The tables that differ between the build database and a full rebuild (empty: identical)."""
    scratch = dataclasses.replace(p, build_db=p.verify_db)
    p.verify_db.unlink(missing_ok=True)
    con = db.connect(scratch)
    try:
        for layer in layers:
            build.run(con, scratch, layer, echo=echo)
    finally:
        con.close()
    differ = []
    with duckdb.connect() as con:
        con.execute(f"attach '{p.build_db.as_posix()}' as a (read_only)")
        con.execute(f"attach '{p.verify_db.as_posix()}' as b (read_only)")
        mine = set(record.tables(con, record.BUILD_SCHEMAS, "a"))
        rebuilt = set(record.tables(con, record.BUILD_SCHEMAS, "b"))
        for table in sorted(mine | rebuilt):
            if table not in rebuilt:
                differ.append(f"{table}: only in the build database")
            elif table not in mine:
                differ.append(f"{table}: only in the rebuild")
            else:
                ours, theirs = (record.checksum(con, f"{c}.{table}") for c in ("a", "b"))
                if ours[0] != theirs[0]:
                    differ.append(f"{table}: {ours[0]:,} rows against {theirs[0]:,} rebuilt")
                elif ours != theirs:
                    differ.append(f"{table}: same rows, other values")
    if not keep:
        p.verify_db.unlink(missing_ok=True)
    return differ
