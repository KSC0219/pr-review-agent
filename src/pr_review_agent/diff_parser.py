"""Unified diff parsing.

The agents must anchor every comment to a line that the PR actually added, so
the parser tracks new-file line numbers for each added line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class FileDiff:
    path: str
    added: list[tuple[int, str]] = field(default_factory=list)
    lines: list[tuple[str, int | None, str]] = field(default_factory=list)  # (kind, new_line_no, text)

    @property
    def added_line_numbers(self) -> set[int]:
        return {n for n, _ in self.added}


def parse_diff(diff: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    new_no = 0
    in_hunk = False
    for raw in diff.splitlines():
        if raw.startswith("diff --git"):
            current, in_hunk = None, False
            continue
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            if path == "/dev/null":
                current = None
            else:
                current = FileDiff(path=path[2:] if path.startswith("b/") else path)
                files.append(current)
            in_hunk = False
            continue
        if raw.startswith("--- "):
            in_hunk = False
            continue
        match = _HUNK.match(raw)
        if match:
            new_no = int(match.group(1))
            in_hunk = True
            continue
        if current is None or not in_hunk:
            continue
        if raw.startswith("+"):
            current.added.append((new_no, raw[1:]))
            current.lines.append(("+", new_no, raw[1:]))
            new_no += 1
        elif raw.startswith("-"):
            current.lines.append(("-", None, raw[1:]))
        elif raw.startswith("\\"):
            continue
        else:
            current.lines.append((" ", new_no, raw[1:] if raw.startswith(" ") else raw))
            new_no += 1
    return files


def annotate(files: list[FileDiff]) -> str:
    """Render the diff with explicit new-file line numbers for the LLM."""
    out: list[str] = []
    for f in files:
        out.append(f"=== FILE: {f.path} ===")
        for kind, no, text in f.lines:
            label = f"{no:>5}" if no is not None else "     "
            out.append(f"{label} {kind} {text}")
        out.append("")
    return "\n".join(out)
