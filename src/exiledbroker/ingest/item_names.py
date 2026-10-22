"""Map GGG metadata ids (as used by the currency exchange) to item names via RePoE."""

import json
from dataclasses import dataclass

from exiledbroker.config import Settings
from exiledbroker.ingest.http import PoliteClient, download, is_complete


@dataclass(frozen=True)
class BaseItem:
    metadata_id: str
    name: str
    item_class: str


def base_items_path(settings: Settings):
    return settings.repoe_raw_dir / "base_items.min.json"


def ensure_base_items(client: PoliteClient, settings: Settings) -> None:
    """Download RePoE's base item table once (it's a few MB)."""
    download(client, settings.repoe_base_items_url, base_items_path(settings))


def load_base_items(settings: Settings) -> dict[str, BaseItem]:
    path = base_items_path(settings)
    if not is_complete(path):
        raise FileNotFoundError(f"{path} is missing; run `eb exchange sync` first")
    raw = json.loads(path.read_text())
    return {
        k: BaseItem(k, v["name"], v.get("item_class", "")) for k, v in raw.items() if v.get("name")
    }
