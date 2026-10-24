"""The API's result cache: shared by every visitor, bounded, and keyed on the data.

Each entry is keyed on the endpoint, its arguments and the data version (when the
latest load finished). A result is computed once per new hour of data, not once per
request or timer. The size cap matters because some arguments are numbers people
type (fee buffer, score weights): an uncapped cache would grow with use.
tests/test_api.py checks the cap."""

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

MAX_ENTRIES = 256


class ResultCache:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self.max_entries = max_entries
        self._entries: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get_or_compute(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                self.hits += 1
                return self._entries[key]
        value = compute()  # outside the lock: concurrent misses may both compute
        with self._lock:
            self.misses += 1
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
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
