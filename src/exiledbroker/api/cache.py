"""The API's result caches: shared by every visitor, bounded, and keyed on the data.

Each entry is keyed on the endpoint, its arguments and the data version (when the
latest load finished). A result is computed once per new hour of data, not once per
request or timer: concurrent requests for a key that is being computed wait for that
computation instead of starting their own (a traffic spike on an uncached item would
otherwise run the same queries dozens of times at once, against a pool of 5
connections). The size caps matter because the caches would otherwise grow with use;
tests/test_api.py checks them.

There are three: `results` for the pages' tables (a few per league), `items` for
Price check's items, one per item the league's list holds (~900), kept as gzipped bytes
only (api/deps.py), so caching all of them costs ~25 MB, and `previews` for the
pre-launch preview's documents (api/routes/preview.py), stored gzipped, keyed on the
snapshot's version rather than the data's (they don't change with a new hour), and
mostly answered by Cloudflare's edge, which keeps each for a day."""

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

MAX_ENTRIES = 256
MAX_ITEMS = 1024  # a league's Price check list holds ~900 items (Allflame: 876)
MAX_PREVIEWS = 512  # of ~1,300 documents (4 days × ~300 items, + their series); ~15 kB each


class ResultCache:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self.max_entries = max_entries
        self._entries: OrderedDict[Hashable, Any] = OrderedDict()
        self._pending: dict[Hashable, threading.Event] = {}
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get_or_compute(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        while True:
            with self._lock:
                if key in self._entries:
                    self._entries.move_to_end(key)
                    self.hits += 1
                    return self._entries[key]
                pending = self._pending.get(key)
                if pending is None:
                    pending = self._pending[key] = threading.Event()
                    break  # this thread computes
            # Another thread is computing this key: wait, then read its result (or, if
            # it failed or the entry was dropped meanwhile, compute it here).
            pending.wait()
        try:
            value = compute()  # outside the lock: other keys aren't held up
        except BaseException:
            with self._lock:
                del self._pending[key]
            pending.set()
            raise
        with self._lock:
            self.misses += 1
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            del self._pending[key]
        pending.set()
        return value

    def keep_only(self, keep: Callable[[Hashable], bool]) -> int:
        """Drop every entry whose key `keep` rejects; returns how many were dropped."""
        with self._lock:
            gone = [k for k in self._entries if not keep(k)]
            for k in gone:
                del self._entries[k]
        return len(gone)

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = self.misses = 0


results = ResultCache()
items = ResultCache(MAX_ITEMS)
previews = ResultCache(MAX_PREVIEWS)
