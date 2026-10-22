"""Which items count as "currency": poe.ninja's Currency category.

poe.ninja's exchange overview for type=Currency lists every currency item for the
current league, tagged Currency, Catalysts or the league mechanic's own currency.
We keep everything except Catalysts. The list on disk is a running union, so
currency from earlier leagues stays in and new currency is picked up.
"""

from exiledbroker.config import Settings
from exiledbroker.ingest.files import read_json, write_json_atomic
from exiledbroker.ingest.http import PoliteClient

EXCLUDED_CATEGORIES = {"Catalysts"}


def currency_names_path(settings: Settings):
    return settings.raw_dir / "poe_ninja" / "categories" / "currency.json"


def load_currency_names(settings: Settings) -> set[str]:
    return set(read_json(currency_names_path(settings)) or [])


def refresh_currency_names(client: PoliteClient, settings: Settings) -> set[str]:
    """Two small requests: the current league, then its Currency overview."""
    base = f"{settings.poe_ninja_base_url}/poe1/api/economy"
    league = client.get_json(f"{base}/leagues")[0]["id"]
    overview = client.get_json(f"{base}/exchange/current/overview?league={league}&type=Currency")
    names = load_currency_names(settings) | {
        i["name"] for i in overview.get("items", ()) if i.get("category") not in EXCLUDED_CATEGORIES
    }
    write_json_atomic(currency_names_path(settings), sorted(names))
    return names
