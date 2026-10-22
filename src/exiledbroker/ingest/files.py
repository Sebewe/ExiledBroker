import json
import os
from pathlib import Path
from typing import Any


def tmp_path_for(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(path)
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, path)


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
