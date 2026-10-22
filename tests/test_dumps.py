import json
import zipfile
from datetime import date

import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import poe_ninja_dumps as dumps
from exiledbroker.ingest.files import write_json_atomic
from exiledbroker.ingest.http import meta_path_for
from exiledbroker.storage import db
from exiledbroker.storage import dumps as dump_store

ITEMS = """League;Date;Id;Type;Name;BaseType;Variant;Links;Value;Confidence
Mirage;2026-03-07;1;UniqueAccessory;Mageblood;Heavy Belt;;;7798.2;Low
Mirage;2026-03-08;1;UniqueAccessory;Mageblood;Heavy Belt;;;12783.76;High
"""
HC_ITEMS = """League;Date;Id;Type;Name;BaseType;Variant;Links;Value;Confidence
Hardcore Mirage;2026-03-07;1;UniqueAccessory;Mageblood;Heavy Belt;;;9000;Low
"""
CURRENCY = """League;Date;Get;Pay;Value;Confidence
Mirage;2026-03-07;Divine Orb;Chaos Orb;86.2;High
"""

INDEX = [
    {
        "leagueName": "Mirage",
        "minDate": "2026-03-06T00:00:00",
        "maxDate": "2026-07-20T00:00:00",
        "zipName": "Mirage.zip",
    },
    {
        "leagueName": "Ancestors",
        "minDate": "2026-06-25T00:00:00",
        "maxDate": "2026-07-16T00:00:00",
        "zipName": "Ancestors.zip",
    },
]


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.fixture
def mirage(settings):
    dump = next(d for d in dumps.parse_index(INDEX) if d.league_name == "Mirage")
    zp = dumps.zip_path(settings, dump)
    zp.parent.mkdir(parents=True)
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("Mirage.items.csv", ITEMS)
        zf.writestr("Hardcore Mirage.items.csv", HC_ITEMS)
        zf.writestr("Mirage.currency.csv", CURRENCY)
        zf.writestr("Standard.items.csv", ITEMS.replace("Mirage;", "Standard;"))
    write_json_atomic(meta_path_for(zp), {"size": zp.stat().st_size, "last_modified": "x"})
    return dump


def test_parse_index_classifies(settings):
    kinds = {d.league_name: d.kind for d in dumps.parse_index(INDEX)}
    assert kinds == {"Mirage": "challenge", "Ancestors": "event"}


def test_extract_is_idempotent(settings, mirage):
    assert len(dumps.extract_dump(settings, mirage)) == 2
    assert dumps.extract_dump(settings, mirage) == []
    # Toggling hardcore changes the inputs, so that kind is rebuilt.
    rebuilt = dumps.extract_dump(settings, mirage, include_hardcore=True)
    assert [p.parent.name for p in rebuilt] == ["items"]


def test_extract_rejects_unexpected_header(settings, mirage):
    zp = dumps.zip_path(settings, mirage)
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("Mirage.items.csv", "League;Date;Name;Value\n")
        zf.writestr("Mirage.currency.csv", CURRENCY)
    with pytest.raises(ValueError, match="unexpected header"):
        dumps.extract_dump(settings, mirage)


def test_views(settings, mirage):
    dumps.extract_dump(settings, mirage, include_hardcore=True)
    with db.session(settings.db_path) as con:
        db.init_schema(con)
        dump_store.upsert_leagues(con, dumps.parse_index(INDEX))
        assert dump_store.refresh_views(con, settings.dumps_processed_dir) == [
            "dump_item_price",
            "dump_currency_price",
        ]
        rows = db.rows(con, "SELECT hardcore, day_offset FROM dump_item_price ORDER BY 1, 2")
        assert rows == [(False, 1), (False, 2), (True, 1)]
        row = db.rows(con, "SELECT get, value, day_offset FROM dump_currency_price")
        assert row == [("Divine Orb", 86.2, 1)]


def test_league_upsert_updates_existing(settings):
    with db.session(settings.db_path) as con:
        db.init_schema(con)
        dump_store.upsert_leagues(con, dumps.parse_index(INDEX))
        dump_store.upsert_leagues(con, dumps.parse_index(INDEX))
        assert db.scalar(con, "SELECT count(*) FROM league") == 2
        start = db.scalar(con, "SELECT CAST(start_at AS DATE) FROM league WHERE name = 'Mirage'")
        assert start == date(2026, 3, 6)


def test_extract_drops_rows_split_by_line_breaks(settings, mirage):
    # A name with an unquoted line break spills one record over three lines.
    broken = ITEMS + (
        "Mirage;2026-03-09;7;Coffin;Reveals a Random Craft when Buried\n"
        "Rarer Crafts are more common;Reveals a Random Craft when Buried\n"
        "Rarer Crafts are more common;;;5;High\n"
        "Mirage;2026-03-09;1;UniqueAccessory;Mageblood;Heavy Belt;;;15000;High\r\n"
    )
    zp = dumps.zip_path(settings, mirage)
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("Mirage.items.csv", broken)
        zf.writestr("Mirage.currency.csv", CURRENCY)
    dumps.extract_dump(settings, mirage)
    out = dumps.parquet_path(settings, mirage, "items")
    import polars as pl

    df = pl.read_parquet(out)
    assert df["chaos_value"].to_list() == [7798.2, 12783.76, 15000.0]
    assert df["confidence"].to_list()[-1] == "High"  # no stray \r
    assert json.loads(out.with_name(out.name + ".dropped.json").read_text()) == {"rows": 3}
