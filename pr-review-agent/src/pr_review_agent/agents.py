"""The three specialist reviewers and the merge step."""

from __future__ import annotations

from pydantic import ValidationError

from .diff_parser import FileDiff
from .llm import LLM
from .models import SEVERITY_RANK, Finding, Usage

_SHARED = """You are reviewing a pull request on a Java / Spring Boot codebase.
The diff is shown with new-file line numbers. Lines marked "+" were added, "-" removed, " " unchanged.

Rules:
- Only report problems on ADDED (+) lines, and use that line's number.
- Only report problems you are confident about. If nothing is wrong, return an empty list.
- Do not comment on style, naming or formatting.
- Keep each explanation to two sentences and give a concrete fix in `suggestion`.
"""

PROMPTS: dict[str, str] = {
    "bug": _SHARED + """
Your single job: find CORRECTNESS BUGS. Examples: null dereference, Optional.get() without a check,
string comparison with ==, off-by-one errors, resource leaks, swallowed exceptions, wrong arithmetic,
missing break in a switch, modifying a collection while iterating, wrong HTTP status or transaction handling.
Ignore security issues and missing tests; other reviewers cover those.""",
    "security": _SHARED + """
Your single job: find SECURITY VULNERABILITIES. Examples: SQL injection, hardcoded secrets, secrets in logs,
weak hashing (MD5/SHA-1) or insecure randomness for tokens, path traversal, command injection,
missing authorization, permissive CORS, disabled CSRF without reason, unsafe deserialization.
Ignore ordinary bugs and missing tests; other reviewers cover those.""",
    "tests": _SHARED + """
Your single job: find MISSING TEST COVERAGE. Report a finding only when the PR adds a new public method
or a new branch of business logic and the diff contains no test that exercises it.
Anchor the finding on the method declaration line and name the test cases that should exist.
Do not report anything if the PR only refactors, renames, adds logging or documentation,
or already includes matching tests. Ignore bugs and security issues.""",
}

AGENTS = tuple(PROMPTS)


async def run_specialist(agent: str, llm: LLM, annotated_diff: str, files: list[FileDiff]) -> tuple[list[Finding], Usage, int]:
    """Run one reviewer and return (valid findings, usage, number of findings dropped by the guardrail)."""
    raw, usage = await llm.review(agent, PROMPTS[agent], annotated_diff)
    added = {f.path: f.added_line_numbers for f in files}
    kept: list[Finding] = []
    dropped = 0
    for item in raw:
        try:
            finding = Finding(**{**item, "category": agent, "agent": agent})
        except (ValidationError, TypeError):
            dropped += 1
            continue
        # Guardrail: a comment must point at a line this PR added, otherwise
        # GitHub rejects it and it is usually a hallucinated location.
        if finding.line not in added.get(finding.file, set()):
            dropped += 1
            continue
        kept.append(finding)
    return kept, usage, dropped


def merge_findings(findings: list[Finding], max_comments: int) -> list[Finding]:
    """Deduplicate overlapping findings, rank by severity and cap the count."""
    ranked = sorted(findings, key=lambda f: (-SEVERITY_RANK[f.severity], f.file, f.line))
    kept: list[Finding] = []
    for f in ranked:
        duplicate = any(
            k.file == f.file and k.category == f.category and abs(k.line - f.line) <= 2 for k in kept
        )
        if not duplicate:
            kept.append(f)
    return sorted(kept[:max_comments], key=lambda f: (f.file, f.line))


def build_summary(findings: list[Finding]) -> str:
    if not findings:
        return "### Automated review\n\nNo issues found in the changed lines."
    counts = {c: sum(1 for f in findings if f.category == c) for c in ("bug", "security", "tests")}
    lines = [
        "### Automated review",
        "",
        f"Found **{len(findings)}** issue(s): {counts['bug']} bug, {counts['security']} security, {counts['tests']} missing-test.",
        "",
    ]
    for f in findings:
        lines.append(f"- `{f.file}:{f.line}` [{f.category}/{f.severity}] {f.title}")
    return "\n".join(lines)
