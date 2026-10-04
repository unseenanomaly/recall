"""Storage backends. Swap in SQLite/Postgres/Redis by implementing :class:`Store`."""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Iterator, List, Optional

from .models import Memory

FORMAT_VERSION = 1


class Store:
    """In-memory store; also the interface other stores implement."""

    def __init__(self) -> None:
        self._items: Dict[str, Memory] = {}
        #: Small key/value state that isn't a memory (queued notices, hook bookkeeping).
        self.meta: Dict[str, Any] = {}

    def put(self, m: Memory) -> None:
        self._items[m.id] = m

    def get(self, mid: str) -> Optional[Memory]:
        return self._items.get(mid)

    def delete(self, mid: str) -> None:
        self._items.pop(mid, None)

    def all(self) -> List[Memory]:
        return list(self._items.values())

    def flush(self) -> None:
        """Persist pending changes (no-op for in-memory)."""

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Memory]:
        return iter(self.all())


InMemoryStore = Store


class JSONStore(Store):
    """Human-readable, git-diffable persistence in a single JSON file."""

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for d in data.get("memories", []):
                m = Memory.from_dict(d)
                self._items[m.id] = m
            self.meta = dict(data.get("meta") or {})

    def flush(self) -> None:
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        payload = {"version": FORMAT_VERSION, "memories": [m.to_dict() for m in self._items.values()],
                   "meta": self.meta}
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        replace_file(tmp, self.path)


def replace_file(src: str, dst: str, attempts: int = 20) -> None:
    """``os.replace`` that survives Windows briefly locking ``dst`` (antivirus, indexers)."""
    import time
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))


class FileLock:
    """A tiny cross-process lock (no dependencies): ``with FileLock(path + ".lock"): ...``.

    Agents, hooks and the MCP server can all touch the same memory file at once;
    holding this around load -> change -> flush prevents lost updates. A lock older
    than ``stale`` seconds is assumed to belong to a crashed process and is broken.
    """

    def __init__(self, path: str, timeout: float = 5.0, stale: float = 30.0):
        self.path, self.timeout, self.stale = path, timeout, stale
        self._held = False

    def __enter__(self) -> "FileLock":
        import time
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self._held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
                if time.monotonic() > deadline:
                    return self  # give up waiting; proceed unlocked rather than hang an agent
                time.sleep(0.05)

    def __exit__(self, *exc) -> None:
        if self._held:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self._held = False
