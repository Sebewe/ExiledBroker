import re
from dataclasses import dataclass
from datetime import date, datetime

SECONDS_PER_DAY = 86_400

CHALLENGE = "challenge"
RUTHLESS = "ruthless"
EVENT = "event"
LEAGUE_KINDS = (CHALLENGE, RUTHLESS, EVENT)


def day_offset(observed_at: datetime, league_start: datetime) -> float:
    """Days elapsed since the league started; the axis all price curves share."""
    return (observed_at - league_start).total_seconds() / SECONDS_PER_DAY


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def league_id(game: str, name: str) -> str:
    return f"{game}-{slugify(name)}"


@dataclass(frozen=True)
class LeagueWindow:
    name: str
    start: date
    end: date


def classify_league(league: LeagueWindow, all_leagues: list[LeagueWindow]) -> str:
    """Tag a league as challenge, ruthless or event.

    Ruthless leagues are named as such. Events (Phrecia, Ancestors, ...) run inside
    another league's window, so any non-ruthless league nested entirely within a
    longer one is treated as an event.
    """
    if league.name.lower().startswith("ruthless"):
        return RUTHLESS
    for other in all_leagues:
        if other.name == league.name or other.name.lower().startswith("ruthless"):
            continue
        longer = (other.end - other.start) > (league.end - league.start)
        if longer and other.start <= league.start and league.end <= other.end:
            return EVENT
    return CHALLENGE
