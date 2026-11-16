"""Rule-based reviewer.

It serves two purposes: the pipeline can run end to end with no API key, and
the evaluation has a baseline to compare the LLM agents against.
"""

from __future__ import annotations

import re
import time

from .models import Usage

_ROW = re.compile(r"^\s*(\d+) \+ (.*)$")
_FILE = re.compile(r"^=== FILE: (.+) ===$")

BUG_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r'(==|!=)\s*"[^"]*"|"[^"]*"\s*(==|!=)'), "String compared with == instead of equals()", "high"),
    (re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}"), "Exception swallowed by an empty catch block", "medium"),
    (re.compile(r"\.get\(\)\s*[;.]"), "Optional.get() called without checking isPresent()", "high"),
    (re.compile(r"for\s*\(.*<=\s*\w+\.(size\(\)|length)\b"), "Loop bound uses <= and will run past the last index", "high"),
]

SECURITY_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r'"\s*(SELECT|INSERT|UPDATE|DELETE)\b[^"]*"\s*\+', re.I), "SQL built by string concatenation (SQL injection)", "high"),
    (re.compile(r'(password|secret|api_?key|token)\w*\s*=\s*"[^"]{4,}"', re.I), "Hardcoded credential in source code", "high"),
    (re.compile(r'getInstance\(\s*"(MD5|SHA-?1)"', re.I), "Weak hash algorithm", "high"),
    (re.compile(r"log(ger)?\.\w+\(.*(password|secret|token)", re.I), "Sensitive value written to the log", "medium"),
    (re.compile(r"Runtime\.getRuntime\(\)\.exec\("), "Command execution with dynamic input", "high"),
]

_PUBLIC_METHOD = re.compile(r"^\s*public\s+(?!class|interface|enum|record)[\w<>\[\], ?]+\s+(\w+)\s*\(")


def _rows(annotated_diff: str):
    """Yield (file, line_no, text) for every added line."""
    current = ""
    for raw in annotated_diff.splitlines():
        header = _FILE.match(raw)
        if header:
            current = header.group(1)
            continue
        row = _ROW.match(raw)
        if row:
            yield current, int(row.group(1)), row.group(2)


class BaselineLLM:
    async def review(self, agent: str, system: str, annotated_diff: str) -> tuple[list[dict], Usage]:
        started = time.perf_counter()
        rows = list(_rows(annotated_diff))
        findings: list[dict] = []
        if agent in ("bug", "security"):
            rules = BUG_RULES if agent == "bug" else SECURITY_RULES
            for file, line, text in rows:
                for pattern, title, severity in rules:
                    if pattern.search(text):
                        findings.append(
                            {"file": file, "line": line, "severity": severity, "title": title,
                             "explanation": f"Matched rule on: `{text.strip()}`"}
                        )
                        break
        elif agent == "tests":
            touches_tests = any("/test/" in f or f.endswith("Test.java") for f, _, _ in rows)
            if not touches_tests:
                for file, line, text in rows:
                    m = _PUBLIC_METHOD.match(text)
                    if m and "/main/" in file:
                        findings.append(
                            {"file": file, "line": line, "severity": "medium",
                             "title": f"New public method `{m.group(1)}` has no test",
                             "explanation": "The PR adds a public method but changes no test file."}
                        )
        usage = Usage(agent=agent, latency_ms=round((time.perf_counter() - started) * 1000, 2))
        return findings, usage
