"""The pipeline's health, for the admin page: per league, when the live update last ran
and last succeeded, what failed last, and what the past day cost. Read from ingest_run
(one row per update, failed or not, kept RUN_HISTORY), so it's a few hundred rows a
league at most and summarised in SQL.

SQL here must stay Postgres-compatible: the hosted site's Postgres serves the same queries.
"""

from datetime import datetime, timedelta

import duckdb
import polars as pl

from exiledbroker.storage import db

DAY = timedelta(days=1)


def summary(con: duckdb.DuckDBPyConnection, now: datetime) -> pl.DataFrame:
    """One row per league with recorded updates, the most recently run first. `now` is
    naive UTC, like ingest_run's timestamps; the "past day" counts are from it."""
    since = now - DAY
    out = db.frame(
        con,
        """
        SELECT r.league_id,
               coalesce(max(l.name), r.league_id) AS league,
               max(r.started_at) AS last_run,
               max(r.started_at) FILTER (WHERE r.state <> 'failed') AS last_success,
               max(r.started_at) FILTER (WHERE r.state = 'failed') AS last_failure,
               max(r.latest_hour) AS latest_hour,
               count(*) FILTER (WHERE r.started_at >= ?) AS runs_day,
               count(*) FILTER (WHERE r.started_at >= ? AND r.state = 'failed')
                   AS failures_day,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.seconds)
                   FILTER (WHERE r.started_at >= ?) AS median_seconds_day,
               coalesce(sum(r.requests) FILTER (WHERE r.started_at >= ?), 0) AS requests_day,
               coalesce(sum(r.bytes_received) FILTER (WHERE r.started_at >= ?), 0)
                   AS bytes_day,
               coalesce(sum(r.hours_added) FILTER (WHERE r.started_at >= ?), 0)
                   AS hours_added_day
        FROM ingest_run r
        LEFT JOIN league l ON l.id = r.league_id
        GROUP BY r.league_id
        """,
        [since] * 6,
    )
    errors = db.frame(
        con,
        """
        SELECT r.league_id, r.error AS last_error, r.state AS last_state
        FROM ingest_run r
        JOIN (SELECT league_id, max(started_at) AS started_at
              FROM ingest_run GROUP BY league_id) m
          ON m.league_id = r.league_id AND m.started_at = r.started_at
        """,
    )
    if out.is_empty():
        return out
    return (
        out.join(errors, on="league_id", how="left")
        .sort(["last_run", "league_id"], descending=[True, False])
        .drop("league_id")
    )
