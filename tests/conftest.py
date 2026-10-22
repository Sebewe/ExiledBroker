"""No test may touch the real data/ folder. Anything that falls back to the default
data directory (a forgotten path, a module-scoped fixture) lands in a temp dir.
Set at import, before any fixture of any scope runs; tests may still override it."""

import os
import tempfile

os.environ["EB_DATA_DIR"] = tempfile.mkdtemp(prefix="eb-test-data-")
