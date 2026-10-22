from datetime import datetime

from exiledbroker.normalize.leagues import day_offset


def test_day_offset_is_fractional_days():
    start = datetime(2026, 11, 20, 20, 0)
    assert day_offset(datetime(2026, 11, 22, 8, 0), start) == 1.5
    assert day_offset(start, start) == 0.0
