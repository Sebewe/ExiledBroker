"""The image's memory settings still reach the libraries they're meant for."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
POLARS_RUN = "import polars as pl; pl.DataFrame({'a': [1, 2]}).sum()"


def image_env(name: str) -> str:
    match = re.search(rf"\b{name}=(\S+)", DOCKERFILE.read_text())
    assert match, f"{name} is not set in the Dockerfile"
    return match.group(1)


def polars_stderr(conf: str) -> str:
    env = {"_RJEM_MALLOC_CONF": conf, "PATH": ""}
    run = subprocess.run(
        [sys.executable, "-c", POLARS_RUN], check=True, env=env, capture_output=True
    )
    return run.stderr.decode()


@pytest.mark.skipif(sys.platform != "linux", reason="polars uses jemalloc on Linux only")
def test_polars_reads_the_images_allocator_setting():
    # A bad option is reported, so polars' jemalloc reads this variable (a polars
    # upgrade that drops jemalloc or renames its prefix would fail here)...
    assert "Invalid conf pair" in polars_stderr("not_an_option:1")
    # ...and the image's setting is accepted as it is.
    assert polars_stderr(image_env("_RJEM_MALLOC_CONF")) == ""
