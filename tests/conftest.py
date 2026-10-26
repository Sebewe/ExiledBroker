"""No test may touch the real data/ folder. Anything that falls back to the default
data directory (a forgotten path, a module-scoped fixture) lands in a temp dir.
Set at import, before any fixture of any scope runs; tests may still override it."""

import os
import tempfile

os.environ["EB_DATA_DIR"] = tempfile.mkdtemp(prefix="eb-test-data-")
# Nor the site's Postgres or its off-site backup from a developer's .env: tests that
# need one say so (a throwaway Postgres, never the hosted ones).
os.environ["EB_DATABASE_URL"] = ""
os.environ["EB_BACKUP_URL"] = ""
os.environ["EB_HEALTHCHECK_URL"] = ""  # nor a monitoring service
os.environ["EB_ADMIN_TOKEN"] = ""  # the admin API is off unless a test sets a token
os.environ["EB_ORIGIN_KEY"] = ""  # nor the hosted origin's Cloudflare-only check


import pytest


@pytest.fixture(autouse=True)
def _fresh_api_caches(monkeypatch):
    """Each test starts with empty API caches and sees new data at once (the API trusts
    a data version for VERSION_TTL seconds; tests that check that set it themselves)."""
    from exiledbroker.api import deps

    deps.reset()
    monkeypatch.setattr(deps, "VERSION_TTL", 0.0)
    yield
    deps.reset()
