import zipfile

import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import poe_ninja_dumps as dumps
from exiledbroker.ingest.files import write_json_atomic
from exiledbroker.ingest.http import meta_path_for
from exiledbroker.normalize import dump_loader
from exiledbroker.services import overview
from exiledbroker.storage import db
from exiledbroker.storage import dumps as dump_store

INDEX = [
    {
        "leagueName": "Mirage",
        "minDate": "2026-03-06T00:00:00",
        "maxDate": "2026-07-20T00:00:00",
        "zipName": "Mirage.zip",
    },
]
ITEMS = """League;Date;Id;Type;Name;BaseType;Variant;Links;Value;Confidence
Mirage;2026-03-07;1;UniqueAccessory;Mageblood;Heavy Belt;;;8000;Low
Mirage;2026-03-08;1;UniqueAccessory;Mageblood;Heavy Belt;;;12000;High
Mirage;2026-03-08;2;SkillGem;Perforate;Perforate;21/20c;;5;High
Mirage;2026-03-08;5;BaseType;Leather Belt;Leather Belt;;;3;High
Mirage;2026-03-08;6;Scarab;Gilded Breach Scarab;Gilded Breach Scarab;;;2;High
Mirage;2026-03-08;8;UniqueRelic;;Censer Relic;;;40;Low
Mirage;2026-03-08;3;UniqueArmour;Tabula Rasa;Simple Robe;;6 links;20;High
Mirage;2026-03-08;4;UniqueArmour;Zero Value;Simple Robe;;;0;Low
Hardcore Mirage;2026-03-08;1;UniqueAccessory;Mageblood;Heavy Belt;;;99999;Low
"""
CURRENCY = """League;Date;Get;Pay;Value;Confidence
Mirage;2026-03-07;Divine Orb;Chaos Orb;80;High
Mirage;2026-03-07;Chaos Orb;Divine Orb;0.0125;Low
Mirage;2026-03-08;Divine Orb;Chaos Orb;100;High
Mirage;2026-03-08;Orb of Fusing;Chaos Orb;0.5;Medium
"""


@pytest.fixture
def setup(tmp_path):
    settings = Settings(data_dir=tmp_path)
    index = dumps.parse_index(INDEX)
    dump = index[0]
    zp = dumps.zip_path(settings, dump)
    zp.parent.mkdir(parents=True)
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("Mirage.items.csv", ITEMS)
        zf.writestr("Mirage.currency.csv", CURRENCY)
    write_json_atomic(meta_path_for(zp), {"size": zp.stat().st_size, "last_modified": "x"})
    dumps.extract_dump(settings, dump)
    con = db.connect(settings.db_path)
    db.init_schema(con)
    dump_store.upsert_leagues(con, index)
    yield settings, dump, con
    con.close()


def price(con, item_id, day):
    q = """SELECT chaos_value, divine_value, chaos_ask, chaos_bid, confidence
           FROM price_observation WHERE item_id = ? AND day_offset = ?"""
    return db.rows(con, q, [item_id, day])[0]


def test_load_keeps_currency_and_uniques(setup):
    settings, dump, con = setup
    result = dump_loader.load_league(con, settings, dump)
    # Mageblood + Tabula (uniques), scarab, Divine + Fusing. Gems, bases, zero values
    # and hardcore rows are dropped.
    assert (result.items, result.rows) == (5, 7)
    categories = dict(db.rows(con, "SELECT id, category FROM item"))
    assert categories == {
        "ninja:1": "UniqueAccessory",
        "ninja:3": "UniqueArmour",
        "currency:gilded-breach-scarab": "scarab",
        "currency:divine-orb": "currency",
        "currency:orb-of-fusing": "currency",
    }

    assert price(con, "ninja:1", 2) == (12000, 120, None, None, "High")
    # Divine: both sides on day 1 -> midpoint, weaker confidence wins.
    assert price(con, "currency:divine-orb", 1) == (80, 1, 80, 80, "Low")
    assert price(con, "currency:orb-of-fusing", 2)[:2] == (0.5, 0.005)
    assert db.scalar(con, "SELECT links FROM item WHERE id = 'ninja:3'") == 6
    tracked = db.rows(con, "SELECT item_id, group_id FROM tracked_item ORDER BY 1")
    assert tracked == [
        ("currency:divine-orb", "currency"),
        ("currency:gilded-breach-scarab", "scarab"),
    ]


def test_reload_is_skipped_and_force_replaces(setup):
    settings, dump, con = setup
    dump_loader.load_league(con, settings, dump)
    assert dump_loader.load_league(con, settings, dump).skipped
    again = dump_loader.load_league(con, settings, dump, force=True)
    assert not again.skipped
    assert db.scalar(con, "SELECT count(*) FROM price_observation") == 7


def test_interrupted_load_rolls_back(setup, monkeypatch):
    settings, dump, con = setup
    real_scalar = db.scalar

    def interrupt(con_, sql, params=None):
        if "stage_price" in sql:
            raise KeyboardInterrupt
        return real_scalar(con_, sql, params)

    monkeypatch.setattr(dump_loader.db, "scalar", interrupt)
    with pytest.raises(KeyboardInterrupt):
        dump_loader.load_league(con, settings, dump)
    monkeypatch.undo()

    assert db.scalar(con, "SELECT count(*) FROM price_observation") == 0
    assert db.scalar(con, "SELECT count(*) FROM item") == 0
    assert db.scalar(con, "SELECT count(*) FROM ingest_load") == 0
    assert not dump_loader.load_league(con, settings, dump).skipped


def test_services_read_loaded_tables(setup):
    settings, dump, con = setup
    dump_loader.load_league(con, settings, dump)
    assert overview.leagues_with_prices(con).rows() == [("Mirage", "challenge")]
    cal = overview.league_calendar(con)
    assert cal.filter(cal["name"] == "Mirage")["price_rows"].item() == 7
