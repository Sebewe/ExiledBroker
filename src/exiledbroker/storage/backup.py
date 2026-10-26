"""The off-site backup (docs/supabase.md): a copy of the site's database in a second
provider, kept by the hosted pipeline and read back only to restore.

The site runs on Railway (web, Postgres, the hourly pipeline), where the services
reach the database over a free private network. Supabase's free tier keeps a copy:
after each pass the pipeline calls `sync(site, backup)`. Supabase bills what is read
out of it, not what is written in, so a sync uploads the changes and reads back only
enough to know what they are (which hours it has, a few checksums and counts: tens of
kB). The one bulk read is a restore, `sync(backup, site)`, after losing Railway's
database.

`sync(src, dst)` makes `dst` hold what `src` holds, incrementally and in one
transaction on `dst` (always Postgres):
- per league: the hours `src` has loaded that `dst` hasn't (price and loop rows, in
  chunks of hours), deleting the hours `dst` has that `src` doesn't;
- the shared tables (leagues, items, tracked items, cards): rows that differ, and the
  tracked items and cards `src` no longer has deleted;
- reference data: metadata always, the content (RePoE's is ~1 MB) only when its MD5
  differs;
- the tables built from past leagues (`site.REPLACED_TABLES`), each group replaced when
  its stamp (a few counts and build times, `_stamps`) differs: the Launch tables, the
  backtest report, the sell helper report (the hour-of-day and stack constants) and Price
  check's paths (once a league: ~25k rows, ~3 MB);
- the raw pages of the window (from `src`'s `exchange_page`, or from disk for the
  local copy), and none outside it;
- leagues `dst` has and `src` doesn't: dropped (a league switch).

`src` is either a site database (Postgres, or a DuckDB file in tests), mirrored whole,
or the local research DuckDB (all history), of which only the named leagues are
copied, filtered as `site.seed` does. From the local copy, hours newer than it has are
never deleted from `dst`: the backup may be ahead of a local copy that's behind.

A league loaded by a different LOADER_VERSION (a deploy that rebuilt it) is deleted
from `dst` in a transaction of its own, and its space returned (VACUUM FULL) before
it's copied again, so a rebuild doesn't grow the backup on a 500 MB plan."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.storage import db, site

CHUNK_HOURS = 48  # hours of rows per copy: bounds memory on a rebuild or a restore
CHUNK_PAGES = 24  # raw pages per copy (up to ~1.5 MB each in a launch's first hours)
# The hourly tables, with their time column and how they're filtered to the site's rows.
HOURLY_TABLES = [
    ("price_observation", "observed_at", " AND source = ?"),
    ("cross_market_hour", "observed_at", ""),
    ("exchange_hour_loaded", "hour", ""),
]


@dataclass
class LeagueSync:
    hours_added: int = 0
    hours_removed: int = 0
    rows_added: int = 0
    rebuilt: bool = False


@dataclass
class SyncResult:
    leagues: dict[str, LeagueSync] = field(default_factory=dict)
    pages_added: int = 0
    pages_removed: int = 0
    tables: list[str] = field(default_factory=list)  # shared / replaced tables updated
    dropped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    title: str = "Backup"  # what the copy is, for the log line

    @property
    def changed(self) -> bool:
        return bool(
            any(s.hours_added or s.hours_removed or s.rebuilt for s in self.leagues.values())
            or self.pages_added
            or self.pages_removed
            or self.tables
            or self.dropped
        )

    def __str__(self) -> str:
        if not self.changed:
            out = f"{self.title}: up to date."
        else:
            parts = []
            for lid, s in self.leagues.items():
                if s.hours_added or s.hours_removed or s.rebuilt:
                    rebuilt = " (rebuilt)" if s.rebuilt else ""
                    parts.append(
                        f"{lid} +{s.hours_added}/-{s.hours_removed} hours, "
                        f"+{s.rows_added:,} rows{rebuilt}"
                    )
            if self.pages_added or self.pages_removed:
                parts.append(f"pages +{self.pages_added}/-{self.pages_removed}")
            if self.tables:
                parts.append(f"updated {', '.join(self.tables)}")
            if self.dropped:
                parts.append(f"dropped {', '.join(self.dropped)}")
            out = f"{self.title}: {'; '.join(parts)}."
        for w in self.warnings:
            out += f" Warning: {w}"
        return out


def _in(values) -> str:
    return ", ".join("?" for _ in values)


def _columns(con, table: str) -> list[str]:
    """A table's columns in order, on either engine."""
    q = (
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? AND table_schema = current_schema() ORDER BY ordinal_position"
    )
    return [r[0] for r in db.rows(con, q, [table])]


def _chunks(values: list, size: int):
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _hours(con, lid: str) -> set[datetime]:
    """The league's loaded hours. From Postgres as one compact string of unix times
    (the backup's list is read every pass: ~7 kB instead of ~20 kB of timestamps)."""
    if not db.is_postgres(con):
        q = "SELECT hour FROM exchange_hour_loaded WHERE league_id = ?"
        return {h for (h,) in db.rows(con, q, [lid])}
    q = (
        "SELECT string_agg(extract(epoch FROM hour)::bigint::text, ',') "
        "FROM exchange_hour_loaded WHERE league_id = ?"
    )
    text = db.scalar(con, q, [lid])
    return {cx.from_ts(int(ts)).replace(tzinfo=None) for ts in text.split(",")} if text else set()


def _stored_pages(con) -> set[int]:
    if not db.is_postgres(con):
        return {r[0] for r in db.rows(con, "SELECT hour FROM exchange_page")}
    text = db.scalar(con, "SELECT string_agg(hour::text, ',') FROM exchange_page")
    return {int(h) for h in text.split(",")} if text else set()


def _fingerprint(con, lid: str) -> str | None:
    q = "SELECT fingerprint FROM ingest_load WHERE league_id = ? AND source = ?"
    rows = db.rows(con, q, [lid, site.HOURLY])
    return rows[0][0] if rows else None


def _loaded_leagues(con) -> list[str]:
    q = "SELECT DISTINCT league_id FROM ingest_load WHERE source = ?"
    return sorted(r[0] for r in db.rows(con, q, [site.HOURLY]))


def _upsert_changed(src, dst, table: str, key: list[str], where: str = "", params=()) -> bool:
    """Upsert the `src` rows (`where` selects them) that differ from `dst`'s. Unchanged
    rows aren't rewritten, so they leave no dead space. Returns whether any changed."""
    cols = _columns(src, table)
    rows = db.rows(src, f"SELECT {', '.join(cols)} FROM {table} {where}", list(params))
    if not rows:
        return False
    tmp = f"sync_{table}"
    dst.execute(f"CREATE TEMP TABLE {tmp} (LIKE {table}) ON COMMIT DROP")
    site._copy(dst, tmp, cols, rows)
    names = ", ".join(cols)
    others = [c for c in cols if c not in key]
    updates = ", ".join(f"{c} = excluded.{c}" for c in others)
    differs = " OR ".join(f"{table}.{c} IS DISTINCT FROM excluded.{c}" for c in others)
    action = f"DO UPDATE SET {updates} WHERE {differs}" if others else "DO NOTHING"
    changed = dst.execute(
        f"INSERT INTO {table} ({names}) SELECT {names} FROM {tmp} "
        f"ON CONFLICT ({', '.join(key)}) {action}"
    ).rowcount
    dst.execute(f"DROP TABLE {tmp}")
    return changed > 0


def _mirror(src, dst, table: str, key: list[str], where: str = "", params=()) -> bool:
    """Keep `dst`'s table identical to the `src` rows `where` selects: changed rows
    upserted, rows `src` no longer has deleted (an item leaving the core pool leaves
    the site). Once `src`'s rows are in, `dst` has stale rows only if it has more rows,
    so its keys are read only then."""
    changed = _upsert_changed(src, dst, table, key, where, params)
    here = db.scalar(src, f"SELECT count(*) FROM {table} {where}", list(params))
    if db.scalar(dst, f"SELECT count(*) FROM {table}") <= here:
        return changed
    q = f"SELECT {', '.join(key)} FROM {table}"
    keep = {tuple(r) for r in db.rows(src, f"{q} {where}", list(params))}
    cond = " AND ".join(f"{k} = ?" for k in key)
    for r in db.rows(dst, q):
        if tuple(r) not in keep:
            db.execute(dst, f"DELETE FROM {table} WHERE {cond}", list(r))
    return True


def _sync_reference(src, dst) -> bool:
    """Reference documents: metadata (when checked, version tags) always; the content
    only when its MD5 differs from `dst`'s."""
    meta = ["fetched_at", "source_url", "etag", "last_modified", "checked_at"]
    types = ["timestamp", "text", "text", "text", "timestamp"]
    theirs = dict(db.rows(dst, "SELECT key, md5(content) FROM reference_data"))
    ours = db.rows(src, f"SELECT key, {', '.join(meta)}, md5(content) FROM reference_data")
    changed = False
    for key, *values, digest in ours:
        if theirs.get(key) != digest:
            content = db.scalar(src, "SELECT content FROM reference_data WHERE key = ?", [key])
            cols = ["key", *meta, "content"]
            db.execute(
                dst,
                f"INSERT INTO reference_data ({', '.join(cols)}) VALUES ({_in(cols)}) "
                "ON CONFLICT (key) DO UPDATE SET "
                + ", ".join(f"{c} = excluded.{c}" for c in cols[1:]),
                [key, *values, content],
            )
            changed = True
            continue
        sets = ", ".join(f"{c} = %s::{t}" for c, t in zip(meta, types, strict=True))
        differs = " OR ".join(
            f"{c} IS DISTINCT FROM %s::{t}" for c, t in zip(meta, types, strict=True)
        )
        n = dst.execute(
            f"UPDATE reference_data SET {sets} WHERE key = %s AND ({differs})",
            [*values, key, *values],
        ).rowcount
        changed = changed or n > 0
    return changed


# The tables built from past leagues (site.REPLACED_TABLES), in the groups that are
# rebuilt together, each replaced whole when its stamp differs.
LAUNCH_TABLES = ["launch_history", "launch_window", "launch_pick", "launch_pick_league"]
REPORTS = ["backtest_report", "sell_helper_report"]
PRICE_TABLES = ["price_path_league", "price_path", "price_path_constant"]  # Price check's
assert {*LAUNCH_TABLES, *REPORTS, *PRICE_TABLES} == set(site.REPLACED_TABLES)


def _stamps(con) -> dict:
    """What changes when a table built from past leagues is rebuilt, read from both
    sides every pass: a few counts and build times (a few hundred bytes from the
    backup), never rows."""
    picks = db.rows(con, "SELECT max(built_at), count(*) FROM launch_window")[0]
    history = db.rows(con, "SELECT league, count(*) FROM launch_history GROUP BY league")
    out = {"launch tables": (tuple(picks), tuple(sorted(history)))}
    for table in REPORTS:
        out[table] = tuple(db.rows(con, f"SELECT count(*), max(built_at) FROM {table}")[0])
    out["price paths"] = _price_stamp(con)
    return out


def _price_stamp(con) -> tuple:
    """Price check's paths change when a league is captured (locally, or by the pipeline
    once the live league's fortnight is over) and its constants when they're refitted.
    68 bytes read from the backup for five leagues, every pass
    (tests/test_backup.py budgets it under 150)."""
    captured = db.rows(con, "SELECT league, count(*) FROM price_path_league GROUP BY league")
    paths = db.scalar(con, "SELECT count(*) FROM price_path")
    fitted = db.rows(con, "SELECT count(*), max(built_at) FROM price_path_constant")[0]
    return (tuple(sorted(captured)), paths, tuple(fitted))


def _replace(src, dst, table: str) -> None:
    """Replace `dst`'s rows of `table` with `src`'s."""
    db.execute(dst, f"DELETE FROM {table}")
    cols = _columns(src, table)
    rows = db.rows(src, f"SELECT {', '.join(cols)} FROM {table}")
    site._copy(dst, table, cols, rows)


def _sync_built(src, dst) -> list[str]:
    """The tables built from past leagues: each group whose stamp differs is replaced.
    Returns what was updated, for the log line."""
    ours, theirs = _stamps(src), _stamps(dst)
    updated = []
    if ours["launch tables"] != theirs["launch tables"]:
        for table in LAUNCH_TABLES:
            _replace(src, dst, table)
        updated.append("launch tables")
    for table in REPORTS:
        if ours[table] != theirs[table]:
            _replace(src, dst, table)
            updated.append(table.replace("_", " "))
    if ours["price paths"] != theirs["price paths"]:
        for table in PRICE_TABLES:
            _replace(src, dst, table)
        updated.append("price paths")
    return updated


def _drop(dst, lid: str) -> None:
    for table in site.LEAGUE_TABLES:
        db.execute(dst, f"DELETE FROM {table} WHERE league_id = ?", [lid])
    db.execute(dst, "UPDATE league SET exchange_tracked = FALSE WHERE id = ?", [lid])


def _empty_league(dst, lid: str) -> None:
    """Delete a league's hourly rows, commit, and give the space back before copying
    it again. A plain VACUUM only marks it reusable, and on the real Allflame data the
    fresh copy still grew the backup from 319 to 439 MB (the indexes don't reuse it):
    VACUUM FULL rewrites what's left, little once the league is gone, and returns the
    space. It locks the tables while it runs; nothing reads the backup."""
    with dst.transaction():
        _drop(dst, lid)
    for table in site.LEAGUE_TABLES:
        dst.execute(f"VACUUM FULL {table}")


def _copy_hours(src, dst, lid: str, hours: list[datetime]) -> int:
    rows_added = 0
    for table, col, extra in HOURLY_TABLES:
        cols = _columns(src, table)
        params = [lid, site.HOURLY] if extra else [lid]
        for chunk in _chunks(hours, CHUNK_HOURS):
            rows = db.rows(
                src,
                f"SELECT {', '.join(cols)} FROM {table} WHERE league_id = ?{extra} "
                f"AND {col} IN ({_in(chunk)})",
                [*params, *chunk],
            )
            site._copy(dst, table, cols, rows)
            if table == "price_observation":
                rows_added += len(rows)
    return rows_added


def _page_hours(src, settings: Settings, research: bool, lids: list[str]) -> list[int]:
    """The raw pages `dst` should hold: a site database's stored pages (its window), or
    the local copy's pages on disk for the leagues' loaded hours."""
    if not research:
        return sorted(_stored_pages(src))
    hours = set()
    for lid in lids:
        hours |= {cx.to_ts(h.replace(tzinfo=UTC)) for h in _hours(src, lid)}
    return sorted(h for h in hours if cx.page_path(settings, h).exists())


def _page_bodies(src, settings: Settings, research: bool, hours: list[int]):
    """(hour, gzipped body) for `hours`, in chunks, from `src` or from disk."""
    for chunk in _chunks(hours, CHUNK_PAGES):
        if research:
            yield [(h, cx.page_path(settings, h).read_bytes()) for h in chunk]
        else:
            q = f"SELECT hour, body FROM exchange_page WHERE hour IN ({_in(chunk)})"
            yield [(h, bytes(b)) for h, b in db.rows(src, q, chunk)]


def _sync_pages(src, dst, settings: Settings, research: bool, lids: list[str]) -> tuple[int, int]:
    want = _page_hours(src, settings, research, lids)
    have = _stored_pages(dst)
    missing = [h for h in want if h not in have]
    added = 0
    for batch in _page_bodies(src, settings, research, missing):
        site._copy(dst, "exchange_page", ["hour", "body"], batch)
        added += len(batch)
    extra = sorted(have - set(want))
    if extra:
        db.execute(dst, f"DELETE FROM exchange_page WHERE hour IN ({_in(extra)})", extra)
    return added, len(extra)


def sync(src, dst, settings: Settings, leagues: list[str] | None = None) -> SyncResult:
    """Make `dst` (Postgres) hold what `src` holds; see the module doc. `leagues` (names)
    are required from the local research copy and ignored from a site database, which
    is mirrored whole. Pages come from `src`'s `exchange_page` when it's a site
    database, else from disk (`settings`)."""
    if not getattr(dst, "autocommit", False):
        raise ValueError("connect to the copy with autocommit=True (sync manages its transactions)")
    research = not db.is_postgres(src) and leagues is not None
    if research:
        lids = [
            r[0]
            for r in db.rows(src, f"SELECT id FROM league WHERE name IN ({_in(leagues)})", leagues)
        ]
        if len(lids) != len(leagues):
            raise LookupError(f"not all of {', '.join(leagues)} are in the local database")
    else:
        lids = _loaded_leagues(src)
    db.init_schema(dst)
    result = SyncResult()

    # A league a different loader version rebuilt: emptied first, outside the main
    # transaction, so the copy below reuses its space.
    for lid in lids:
        theirs = _fingerprint(dst, lid)
        if theirs is not None and theirs != _fingerprint(src, lid):
            _empty_league(dst, lid)
            result.leagues[lid] = LeagueSync(rebuilt=True)

    with dst.transaction():
        ids = _in(lids)
        if research:
            league_where, league_params = f"WHERE id IN ({ids})", lids
            used = (
                f"SELECT item_id FROM price_observation WHERE league_id IN ({ids}) AND source = ? "
                f"UNION SELECT item_id FROM cross_market_hour WHERE league_id IN ({ids})"
            )
            used_params = [*lids, site.HOURLY, *lids]
            item_where, item_params = f"WHERE id IN ({used})", used_params
            tracked_where, tracked_params = f"WHERE item_id IN ({used})", used_params
        else:
            league_where = item_where = tracked_where = ""
            league_params = item_params = tracked_params = []
        # Parents first: the rows below refer to leagues and items.
        if _upsert_changed(src, dst, "league", ["id"], league_where, league_params):
            result.tables.append("league")
        if lids and _upsert_changed(src, dst, "item", ["id"], item_where, item_params):
            result.tables.append("item")
        if _mirror(
            src, dst, "tracked_item", ["item_id", "group_id"], tracked_where, tracked_params
        ):
            result.tables.append("tracked_item")
        if _mirror(src, dst, "divination_card", ["item_id"]):
            result.tables.append("divination_card")
        if _sync_reference(src, dst):
            result.tables.append("reference_data")

        for lid in lids:
            s = result.leagues.setdefault(lid, LeagueSync())
            ours, theirs = _hours(src, lid), _hours(dst, lid)
            add = sorted(ours - theirs)
            remove = theirs - ours
            if research and ours:  # never hours newer than the local copy has
                remove = {h for h in remove if h < max(ours)}
            remove = sorted(remove)
            for chunk in _chunks(remove, CHUNK_HOURS):
                for table, col, extra in HOURLY_TABLES:
                    params = [lid, site.HOURLY] if extra else [lid]
                    db.execute(
                        dst,
                        f"DELETE FROM {table} WHERE league_id = ?{extra} AND {col} IN ({_in(chunk)})",
                        [*params, *chunk],
                    )
            s.rows_added = _copy_hours(src, dst, lid, add)
            s.hours_added, s.hours_removed = len(add), len(remove)
            # The load's stamp last: its loaded_at is the site's data version.
            _upsert_changed(
                src,
                dst,
                "ingest_load",
                ["league_id", "source"],
                "WHERE league_id = ? AND source = ?",
                [lid, site.HOURLY],
            )

        for lid in sorted(set(_loaded_leagues(dst)) - set(lids)):
            _drop(dst, lid)
            result.dropped.append(lid)
        # A site database's leagues exactly, once the dropped ones' rows are gone.
        mirrored = not research and _mirror(src, dst, "league", ["id"])
        if mirrored and "league" not in result.tables:
            result.tables.append("league")

        result.tables += _sync_built(src, dst)

        result.pages_added, result.pages_removed = _sync_pages(src, dst, settings, research, lids)

        for lid in lids:  # cheap counts on both sides: a mismatch means a sync bug
            for table, _, extra in HOURLY_TABLES[:2]:
                params = [lid, site.HOURLY] if extra else [lid]
                q = f"SELECT count(*) FROM {table} WHERE league_id = ?{extra}"
                here, there = db.scalar(src, q, params), db.scalar(dst, q, params)
                ahead = research and bool(_hours(dst, lid) - _hours(src, lid))
                if here != there and not ahead:
                    result.warnings.append(
                        f"{lid} {table}: {here:,} rows here, {there:,} in the copy"
                    )
    return result


CONNECT_TIMEOUT = 10  # seconds: an unreachable backup mustn't hold up the pass


def back_up(settings: Settings) -> SyncResult:
    """The hosted pipeline's backup: sync the site's database (EB_DATABASE_URL, else the
    local DuckDB file, as in tests) to EB_BACKUP_URL."""
    import psycopg

    with psycopg.connect(
        settings.backup_url, autocommit=True, connect_timeout=CONNECT_TIMEOUT
    ) as dst:
        if settings.database_url:
            with psycopg.connect(settings.database_url, autocommit=True) as src:
                return sync(src, dst, settings)
        with db.session(settings.db_path, read_only=True) as src:
            return sync(src, dst, settings)
