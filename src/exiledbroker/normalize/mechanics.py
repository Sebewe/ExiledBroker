"""Mechanic baskets for the Farming page: what each league mechanic drops.

The baskets are curated by hand in config/mechanics.toml (docs/farming.md, workstream A),
by exact item name as stored (`item.canonical_name`), so they work for every source.
A mechanic's outputs are its basket; `legacy` outputs left the game and only feed past
leagues' curves; `inputs` (scarabs, astrolabes) are what running it costs. What the site
shows is still limited to the core drop pool (ingest/core_pool.py).

`check` resolves every name against the database and reports what doesn't resolve,
which outputs the core pool doesn't have yet, and how many traded in each league
(`eb mechanics check`). It reads only the database and makes no requests.
"""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from exiledbroker.config import Settings
from exiledbroker.ingest.core_pool import CorePool
from exiledbroker.normalize.tracked import GROUPS, currency_item_id
from exiledbroker.storage import db

LISTS = ("outputs", "groups", "legacy", "inputs")
FIELDS = {"id", "name", "note", *LISTS}
ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class MechanicsError(ValueError):
    """config/mechanics.toml is malformed."""


@dataclass(frozen=True)
class Mechanic:
    id: str
    name: str
    outputs: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()  # price-mapping groups whose items are all outputs
    legacy: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    note: str | None = None

    def names(self) -> tuple[str, ...]:
        """Every item named in the mechanic (outputs, legacy outputs and inputs)."""
        return self.outputs + self.legacy + self.inputs


def _names(entry: dict, key: str, where: str) -> tuple[str, ...]:
    value = entry.get(key, [])
    if not isinstance(value, list) or not all(isinstance(n, str) and n.strip() for n in value):
        raise MechanicsError(f"{where}: {key} must be a list of names")
    dupes = sorted({n for n in value if value.count(n) > 1})
    if dupes:
        raise MechanicsError(f"{where}: {key} lists {', '.join(dupes)} twice")
    return tuple(value)


def parse(raw: dict, source: str = "mechanics.toml") -> list[Mechanic]:
    """Mechanics from a parsed TOML document, validated; raises MechanicsError."""
    if set(raw) - {"mechanic"}:
        raise MechanicsError(f"{source}: unknown keys {sorted(set(raw) - {'mechanic'})}")
    entries = raw.get("mechanic", [])
    if not isinstance(entries, list):
        raise MechanicsError(f"{source}: mechanics are [[mechanic]] tables")
    group_ids = {g.id for g in GROUPS}
    mechanics: list[Mechanic] = []
    for i, entry in enumerate(entries):
        where = f"{source}: mechanic {entry.get('id', i + 1)!r}"
        if set(entry) - FIELDS:
            raise MechanicsError(f"{where}: unknown keys {sorted(set(entry) - FIELDS)}")
        mid, name, note = entry.get("id"), entry.get("name"), entry.get("note")
        if not isinstance(mid, str) or not ID_PATTERN.fullmatch(mid):
            raise MechanicsError(f"{where}: id must be lowercase letters, digits and _")
        if not isinstance(name, str) or not name.strip():
            raise MechanicsError(f"{where}: name is required")
        if note is not None and not isinstance(note, str):
            raise MechanicsError(f"{where}: note must be text")
        lists = {key: _names(entry, key, where) for key in LISTS}
        unknown_groups = sorted(set(lists["groups"]) - group_ids)
        if unknown_groups:
            raise MechanicsError(f"{where}: unknown groups {unknown_groups}")
        if not lists["outputs"] and not lists["groups"]:
            raise MechanicsError(f"{where}: needs outputs or groups")
        for a, b in [("outputs", "legacy"), ("outputs", "inputs"), ("legacy", "inputs")]:
            both = sorted(set(lists[a]) & set(lists[b]))
            if both:
                raise MechanicsError(f"{where}: {', '.join(both)} in both {a} and {b}")
        mechanics.append(Mechanic(id=mid, name=name, note=note, **lists))
    for attr in ("id", "name"):
        values = [getattr(m, attr) for m in mechanics]
        dupes = sorted({v for v in values if values.count(v) > 1})
        if dupes:
            raise MechanicsError(f"{source}: mechanic {attr} {', '.join(dupes)} used twice")
    return mechanics


def load(path: Path) -> list[Mechanic]:
    """The mechanics in `path`; none if the file doesn't exist."""
    if not path.exists():
        return []
    with open(path, "rb") as f:
        try:
            raw = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise MechanicsError(f"{path.name}: {e}") from e
    return parse(raw, path.name)


def load_mechanics(settings: Settings) -> list[Mechanic]:
    return load(settings.mechanics_file)


def resolve(con, names: list[str] | tuple[str, ...]) -> dict[str, str]:
    """Name -> item id for the names the database knows (exact, as stored)."""
    ids = {name: currency_item_id(name) for name in names}
    if not ids:
        return {}
    marks = ", ".join("?" for _ in ids)
    known = {
        r[0] for r in db.rows(con, f"SELECT id FROM item WHERE id IN ({marks})", [*ids.values()])
    }
    return {name: item_id for name, item_id in ids.items() if item_id in known}


def group_items(con, group_ids: tuple[str, ...]) -> list[str]:
    """Item ids in the given price-mapping groups (tracked_item)."""
    if not group_ids:
        return []
    marks = ", ".join("?" for _ in group_ids)
    rows = db.rows(
        con, f"SELECT DISTINCT item_id FROM tracked_item WHERE group_id IN ({marks})", [*group_ids]
    )
    return sorted(r[0] for r in rows)


def output_ids(con, mechanic: Mechanic, *, legacy: bool = False) -> list[str]:
    """The mechanic's basket as item ids: its outputs and groups, plus its legacy outputs
    when `legacy` (for past leagues). Names the database doesn't know are skipped."""
    names = mechanic.outputs + (mechanic.legacy if legacy else ())
    ids = set(resolve(con, names).values()) | set(group_items(con, mechanic.groups))
    return sorted(ids)


def _suggestions(con, name: str) -> list[str]:
    """Stored names a misspelt or ambiguous one probably meant."""
    rows = db.rows(
        con,
        "SELECT canonical_name FROM item WHERE id LIKE 'currency:%' "
        "AND (lower(canonical_name) = lower(?) OR canonical_name LIKE ?)",
        [name, f"{name} (%"],
    )
    return sorted({r[0] for r in rows})


POOL_KEY = "mechanics"  # core_pool.SOURCES: the lists only the Farming page reads
SUFFIX = re.compile(r" \([A-Za-z0-9]+\)$")  # "Name (MetadataName)" for an ambiguous name


def in_pool(pool: CorePool, name: str) -> bool | None:
    """Whether the core pool lists the item in any of its lists (price-mapping groups or
    the Farming page's own); None without any snapshot. poe.ninja lists an item by its
    in-game name, so a stored "Name (MetadataName)" is looked up as "Name"."""
    keys = [g.id for g in GROUPS] + [POOL_KEY]
    names = {name, SUFFIX.sub("", name)}
    decisions = [
        True if any(pool.allows(k, n) for n in names) else pool.allows(k, name) for k in keys
    ]
    if any(decisions):
        return True
    return None if all(d is None for d in decisions) else False


@dataclass
class MechanicCheck:
    mechanic: Mechanic
    unknown: list[tuple[str, list[str]]] = field(default_factory=list)  # (name, suggestions)
    outside_pool: list[str] = field(default_factory=list)  # outputs the pool doesn't show
    group_items: int = 0
    traded: dict[str, int] = field(default_factory=dict)  # league -> outputs traded
    legacy_traded: dict[str, int] = field(default_factory=dict)  # league -> legacy traded


def check(con, mechanics: list[Mechanic], pool: CorePool) -> list[MechanicCheck]:
    """Resolve every mechanic's names and count, per exchange league, how many of its
    outputs traded at all (`cross_market_hour`)."""
    leagues = dict(
        db.rows(con, "SELECT id, name FROM league WHERE exchange_tracked ORDER BY launched_at")
    )
    every = sorted({n for m in mechanics for n in m.names()})
    known = resolve(con, every)
    traded: dict[str, set[str]] = {}
    ids = sorted(
        set(known.values()) | set(group_items(con, tuple({g for m in mechanics for g in m.groups})))
    )
    if ids and leagues:
        marks = ", ".join("?" for _ in ids)
        for league_id, item_id in db.rows(
            con,
            f"SELECT DISTINCT league_id, item_id FROM cross_market_hour WHERE item_id IN ({marks})",
            ids,
        ):
            traded.setdefault(item_id, set()).add(league_id)
    results = []
    for m in mechanics:
        result = MechanicCheck(m)
        result.unknown = [(n, _suggestions(con, n)) for n in m.names() if n not in known]
        result.outside_pool = [n for n in m.outputs if n in known and in_pool(pool, n) is False]
        groups = group_items(con, m.groups)
        result.group_items = len(groups)
        outputs = {known[n] for n in m.outputs if n in known} | set(groups)
        legacy = {known[n] for n in m.legacy if n in known}
        for league_id, league in leagues.items():
            result.traded[league] = sum(league_id in traded.get(i, ()) for i in outputs)
            result.legacy_traded[league] = sum(league_id in traded.get(i, ()) for i in legacy)
        results.append(result)
    return results
