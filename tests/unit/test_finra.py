"""FINRA tick-size pilot intervals (T055; research R13). The fixture is an excerpt of FINRA's
public change file, with its CRLF line endings."""

from datetime import date
from pathlib import Path

from sentinel import warehouse
from sentinel.core import reference
from sentinel.ingest import finra

EXCERPT = Path(__file__).parents[1] / "fixtures" / "finra_tick_pilot_excerpt.txt"


def test_intervals_of_the_test_groups():
    got = {(t, g, s): (e, ex) for t, g, s, e, ex in finra.intervals(EXCERPT.read_text())}
    assert got == {
        # C → G1 on 3 Oct 2016; the ticker changed to CULP on 13 Jul 2017, still G1
        ("CFI", "G1", date(2016, 10, 3)): (date(2017, 7, 13), "N"),
        ("CULP", "G1", date(2017, 7, 13)): (date(2018, 10, 1), "N"),
        # C → G2 on 17 Oct 2016, back to C when the pilot ended on 1 Oct 2018
        ("AAME", "G2", date(2016, 10, 17)): (date(2018, 10, 1), "Q"),
        # removed from G2 a week after joining
        ("TOF", "G2", date(2016, 10, 17)): (date(2016, 10, 24), "A"),
    }  # MDGN / GNMX were control only: no rows


def test_tick_pilot_table(tmp_data):
    tmp_data.finra.mkdir(parents=True)
    (tmp_data.finra / finra.FILE).write_bytes(EXCERPT.read_bytes())
    con = warehouse.connect(tmp_data)
    assert reference.build_tick_pilot(con, tmp_data) == 4
    assert (
        con.execute("select count(*) from core.tick_pilot where pilot_group = 'G2'").fetchone()[0]
        == 2
    )
    con.close()


def test_no_file_no_table(tmp_data):
    con = warehouse.connect(tmp_data)
    assert reference.build_tick_pilot(con, tmp_data) is None
    con.close()
