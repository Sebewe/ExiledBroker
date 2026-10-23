"""The Backtest page's report: built locally by `analysis/backtest` (it needs past
leagues' hours, which the site doesn't hold) and stored as one JSON document."""

import json

from exiledbroker.storage import db

REPORT = "backtest_report"


def report(con) -> list[dict]:
    """The stored report (a one-item list), or nothing before `eb backtest run`."""
    rows = db.rows(con, f"SELECT body FROM {REPORT} WHERE id = 'latest'")
    return [json.loads(rows[0][0])] if rows else []


def built_at(con):
    """When the report was built: the view's stamp (it changes only with `eb backtest
    run` and a seed or publish, not every hour)."""
    return db.scalar(con, f"SELECT max(built_at) FROM {REPORT}")
