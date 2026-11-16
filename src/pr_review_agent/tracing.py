"""Step-level tracing to a JSONL file: one line per graph node execution."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path


class Tracer:
    def __init__(self, path: str | None):
        self.path = Path(path) if path else None
        self.events: list[dict] = []

    def record(self, review_id: str, node: str, duration_ms: float, **fields) -> None:
        event = {"ts": round(time.time(), 3), "review_id": review_id, "node": node,
                 "duration_ms": round(duration_ms, 1), **fields}
        self.events.append(event)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")

    @contextmanager
    def span(self, review_id: str, node: str):
        fields: dict = {}
        started = time.perf_counter()
        try:
            yield fields
        except Exception as exc:
            fields["error"] = repr(exc)
            raise
        finally:
            self.record(review_id, node, (time.perf_counter() - started) * 1000, **fields)
