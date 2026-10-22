import pytest

from exiledbroker.ingest.loot_filter import parse_card_tiers
from exiledbroker.normalize.divination import cards_from_base_items, parse_reward


def test_parse_card_tiers():
    from test_currency_exchange import FILTER

    tiers = parse_card_tiers(FILTER)
    # A card in two blocks keeps the first (here the t1 Show block).
    assert tiers == {
        "House of Mirrors": ("t1", True),
        "The Doctor": ("t1", True),
        "The Hoarder": ("t4", True),
        "Rain of Chaos": ("t5", False),
    }
    with pytest.raises(ValueError):
        parse_card_tiers('Show\n\tClass == "Currency"\n')


@pytest.mark.parametrize(
    "text, expected",
    [
        ("<currencyitem>{10x Exalted Orb}", ("currency", "Exalted Orb", 10)),
        ("<currencyitem>{Mirror of Kalandra}", ("currency", "Mirror of Kalandra", 1)),
        ("<uniqueitem>{Headhunter}", ("unique", "Headhunter", 1)),
        ("<divination>{The Doctor}", ("divination", "The Doctor", 1)),
        (
            "<gemitem>{Level 21 Spell Gem}\r\n<corrupted>{Corrupted}",
            ("gem", "Level 21 Spell Gem", 1),
        ),
        (
            (
                "<size:31>{<magicitem>{Bloodthirsty Eternal Sword}\r\n<default>{Item Level:} "
                "<normal>{66}}"
            ),
            ("magic", "Bloodthirsty Eternal Sword", 1),
        ),
        (
            "<currencyitem>{1,500x Vivid Crystallised Lifeforce}",
            ("currency", "Vivid Crystallised Lifeforce", 1500),
        ),
        ("<currencyitem>{5x Currency}", ("currency", "Currency", 5)),
        ("Disabled", (None, None, None)),
        (" ", (None, None, None)),
    ],
)
def test_parse_reward(text, expected):
    assert parse_reward(text) == expected


def test_cards_from_base_items():
    raw = {
        "Metadata/Items/DivinationCards/DivinationCardTheHoarder": {
            "name": "The Hoarder",
            "item_class": "DivinationCard",
            "release_state": "released",
            "properties": {"description": "<currencyitem>{Exalted Orb}", "stack_size": 12},
        },
        "Metadata/Items/DivinationCards/DivinationCardTheDoctor": {
            "name": "The Doctor",
            "item_class": "DivinationCard",
            "release_state": "released",
            "properties": {"description": "<uniqueitem>{Headhunter}", "stack_size": 8},
        },
        "Metadata/Items/DivinationCards/Unreleased": {
            "name": "Nope",
            "item_class": "DivinationCard",
            "release_state": "unreleased",
            "properties": {},
        },
        "Metadata/Items/DivinationCards/DivinationCardEmperorsLuck": {
            "name": "Emperor's Luck",
            "item_class": "DivinationCard",
            "release_state": "released",
            "properties": {"description": "<currencyitem>{5x Currency}", "stack_size": 5},
        },
        "Metadata/Items/Currency/CurrencyAddModToRare": {
            "name": "Exalted Orb",
            "item_class": "StackableCurrency",
            "release_state": "released",
        },
    }
    cards = {c.name: c for c in cards_from_base_items(raw)}
    assert set(cards) == {"The Hoarder", "The Doctor", "Emperor's Luck"}
    hoarder = cards["The Hoarder"]
    assert (hoarder.item_id, hoarder.stack_size, hoarder.reward_item_id) == (
        "currency:the-hoarder",
        12,
        "currency:exalted-orb",
    )
    assert hoarder.reward_fixed
    # Unique rewards aren't priced on the exchange, so there's no reward item id yet,
    # and whether they're fixed isn't decided yet either.
    assert cards["The Doctor"].reward_item_id is None
    assert cards["The Doctor"].reward_fixed is None
    # "5x Currency" is random: no single item to price.
    luck = cards["Emperor's Luck"]
    assert not luck.reward_fixed and luck.reward_item_id is None


def test_score_turn_ins_ranks_and_tunes():
    import polars as pl

    from exiledbroker.services.divination import score_turn_ins

    summary = pl.DataFrame(
        {
            "name": ["cheap steady", "pricey steady", "loser", "unpriced"],
            "hours": [100, 100, 100, 0],
            "margin_pct": [0.5, 0.05, -0.9, None],
            "set_cost": [1.0, 2000.0, 50.0, None],
            "profitable_share": [0.95, 1.0, 0.0, None],
            "sets_traded": [5000.0, 200.0, 10.0, None],
        }
    )
    cheap = score_turn_ins(summary)
    assert cheap["name"].to_list() == ["cheap steady", "pricey steady", "loser"]  # unpriced dropped
    assert cheap.filter(name="cheap steady")["margin_rank"].item() == 1.0
    assert cheap.filter(name="loser")["profitable_hours_rank"].item() == pytest.approx(1 / 3)
    # Only investment, preferring bigger sets: the 2000c set wins.
    big = score_turn_ins(summary, {"investment": 1.0}, prefer_cheaper_sets=False)
    assert big["name"][0] == "pricey steady" and big["score"][0] == 1.0
    assert score_turn_ins(summary, {"margin": 0.0})["score"].is_null().all()
