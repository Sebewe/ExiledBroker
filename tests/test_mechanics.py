from datetime import datetime

import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest.core_pool import CorePool
from exiledbroker.normalize import mechanics as mech
from exiledbroker.normalize.tracked import currency_item_id
from exiledbroker.storage import db


def test_committed_config_is_valid():
    mechanics = mech.load_mechanics(Settings())
    assert len(mechanics) >= 15
    assert all(m.outputs or m.groups for m in mechanics)


def _parse(**entry):
    return mech.parse({"mechanic": [{"id": "breach", "name": "Breach", **entry}]})


def test_parse_reads_every_field():
    (m,) = _parse(
        outputs=["Flesh of Xesht"],
        groups=["divination"],
        legacy=["Splinter of Xoph"],
        inputs=["Breach Scarab of the Hive"],
        note="Reworked",
    )
    assert m.outputs == ("Flesh of Xesht",) and m.groups == ("divination",)
    assert m.names() == ("Flesh of Xesht", "Splinter of Xoph", "Breach Scarab of the Hive")
    assert m.note == "Reworked"


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"outputs": ["A"], "weights": [1]}, "unknown keys"),
        ({"outputs": ["A", "A"]}, "twice"),
        ({"outputs": "A"}, "list of names"),
        ({"outputs": ["A"], "inputs": ["A"]}, "both outputs and inputs"),
        ({"outputs": ["A"], "legacy": ["A"]}, "both outputs and legacy"),
        ({"groups": ["uniques"]}, "unknown groups"),
        ({"inputs": ["A"]}, "needs outputs or groups"),
        ({"outputs": ["A"], "note": 3}, "note must be text"),
    ],
)
def test_parse_rejects_malformed_entries(entry, message):
    with pytest.raises(mech.MechanicsError, match=message):
        _parse(**entry)


def test_parse_rejects_bad_or_repeated_ids():
    with pytest.raises(mech.MechanicsError, match="lowercase"):
        mech.parse({"mechanic": [{"id": "Breach", "name": "Breach", "outputs": ["A"]}]})
    twice = [{"id": "breach", "name": f"Breach {i}", "outputs": ["A"]} for i in range(2)]
    with pytest.raises(mech.MechanicsError, match="id breach used twice"):
        mech.parse({"mechanic": twice})
    with pytest.raises(mech.MechanicsError, match="unknown keys"):
        mech.parse({"mechanics": []})


def test_load_missing_file_and_bad_toml(tmp_path):
    assert mech.load(tmp_path / "none.toml") == []
    bad = tmp_path / "bad.toml"
    bad.write_text("[[mechanic]\n")
    with pytest.raises(mech.MechanicsError):
        mech.load(bad)


def test_load_reads_toml(tmp_path):
    path = tmp_path / "m.toml"
    path.write_text('[[mechanic]]\nid = "heist"\nname = "Heist"\noutputs = ["Rogue\'s Marker"]\n')
    assert [m.id for m in mech.load(path)] == ["heist"]


ITEMS = [
    "Flesh of Xesht",
    "Splinter of Xoph",
    "Breach Scarab of the Hive",
    "Fine Delirium Orb (CurrencyAfflictionOrbCurrency)",
    "Fine Delirium Orb (CurrencyAfflictionOrbHarbinger)",
    "The Doctor",
]


@pytest.fixture
def con(tmp_path):
    with db.session(tmp_path / "eb.duckdb") as con:
        db.init_schema(con)
        for lid, name, start in [
            ("poe1-keepers", "Keepers", datetime(2025, 10, 31, 21)),
            ("poe1-mirage", "Mirage", datetime(2026, 3, 6, 20)),
        ]:
            con.execute(
                "INSERT INTO league (id, game, name, start_at, launched_at, exchange_tracked) "
                "VALUES (?, 'poe1', ?, ?, ?, TRUE)",
                [lid, name, start, start],
            )
        for name in ITEMS:
            con.execute(
                "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')",
                [currency_item_id(name), name],
            )
        con.execute(
            "INSERT INTO tracked_item VALUES (?, 'divination', 'Divination cards', 4)",
            [currency_item_id("The Doctor")],
        )
        for league, name in [
            ("poe1-keepers", "Splinter of Xoph"),
            ("poe1-keepers", "Flesh of Xesht"),
            ("poe1-mirage", "Flesh of Xesht"),
            ("poe1-mirage", "The Doctor"),
        ]:
            con.execute(
                "INSERT INTO cross_market_hour (league_id, item_id, observed_at, chaos_price) "
                "VALUES (?, ?, ?, 1.0)",
                [league, currency_item_id(name), datetime(2026, 3, 7)],
            )
        yield con


BREACH = mech.Mechanic(
    id="breach",
    name="Breach",
    outputs=("Flesh of Xesht", "Missing Thing"),
    groups=("divination",),
    legacy=("Splinter of Xoph",),
    inputs=("Breach Scarab of the Hive", "Fine Delirium Orb"),
)


def test_resolve_and_output_ids(con):
    assert mech.resolve(con, ["Flesh of Xesht", "Missing Thing"]) == {
        "Flesh of Xesht": "currency:flesh-of-xesht"
    }
    assert mech.output_ids(con, BREACH) == ["currency:flesh-of-xesht", "currency:the-doctor"]
    assert "currency:splinter-of-xoph" in mech.output_ids(con, BREACH, legacy=True)


def test_check_reports_unknown_names_pool_and_trading(con):
    pool = CorePool(listed={"currency": {"Splinter of Xoph"}, "divination": {"The Doctor"}})
    (result,) = mech.check(con, [BREACH], pool)
    assert result.unknown == [
        ("Missing Thing", []),
        (
            "Fine Delirium Orb",
            [
                "Fine Delirium Orb (CurrencyAfflictionOrbCurrency)",
                "Fine Delirium Orb (CurrencyAfflictionOrbHarbinger)",
            ],
        ),
    ]
    assert result.outside_pool == ["Flesh of Xesht"]
    assert result.group_items == 1
    assert result.traded == {"Keepers": 1, "Mirage": 2}  # Flesh both; the card in Mirage
    assert result.legacy_traded == {"Keepers": 1, "Mirage": 0}


def test_in_pool_without_snapshots_is_undecided():
    assert mech.in_pool(CorePool(), "Flesh of Xesht") is None
    assert mech.in_pool(CorePool(include={"currency": {"Flesh of Xesht"}}), "Flesh of Xesht")
