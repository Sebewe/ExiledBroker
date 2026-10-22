"""Every Streamlit cache must be bounded (cost issue #9): caches are shared by all
visitors and some are keyed on free-typed numbers, so an uncapped one grows forever."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_every_cache_has_max_entries():
    unbounded = []
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                name = ast.unparse(dec.func if isinstance(dec, ast.Call) else dec)
                if name in ("st.cache_data", "st.cache_resource"):
                    kwargs = {k.arg for k in dec.keywords} if isinstance(dec, ast.Call) else set()
                    if "max_entries" not in kwargs:
                        unbounded.append(f"{path.name}:{node.lineno} {node.name}")
    assert not unbounded, f"caches without max_entries: {unbounded}"
