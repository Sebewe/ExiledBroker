from datetime import date, datetime

from exiledbroker.normalize.leagues import (
    LeagueWindow,
    classify_league,
    day_offset,
    league_id,
)


def test_day_offset_is_fractional_days():
    start = datetime(2026, 11, 20, 20, 0)
    assert day_offset(datetime(2026, 11, 22, 8, 0), start) == 1.5
    assert day_offset(start, start) == 0.0


def test_league_id_slug():
    assert league_id("poe1", "Phrecia 2.0") == "poe1-phrecia-2-0"
    assert league_id("poe1", "Ruthless Sanctum") == "poe1-ruthless-sanctum"


def test_classify_league():
    leagues = [
        LeagueWindow("Settlers", date(2024, 7, 26), date(2025, 6, 9)),
        LeagueWindow("Ruthless Settlers", date(2024, 7, 27), date(2024, 9, 5)),
        LeagueWindow("Phrecia", date(2025, 2, 20), date(2025, 4, 23)),
        LeagueWindow("Sanctum", date(2022, 12, 9), date(2023, 4, 4)),
        LeagueWindow("Ruthless Sanctum", date(2022, 12, 9), date(2023, 4, 4)),
    ]
    kinds = {lg.name: classify_league(lg, leagues) for lg in leagues}
    assert kinds == {
        "Settlers": "challenge",
        "Ruthless Settlers": "ruthless",
        "Phrecia": "event",
        "Sanctum": "challenge",
        "Ruthless Sanctum": "ruthless",
    }
