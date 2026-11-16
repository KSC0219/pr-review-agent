"""Where pull requests come from and where reviews go.

`GitHubBackend` talks to the GitHub REST API. `LocalBackend` reads `.diff`
files from a folder and writes reviews next to them as JSON, which makes the
whole pipeline runnable offline (demo, tests and the evaluation set).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import httpx

from .config import Settings

GITHUB_API = "https://api.github.com"


class PRBackend(Protocol):
    def get_pr_diff(self, repo: str, pr_number: str) -> str: ...
    def get_file_content(self, repo: str, path: str, ref: str) -> str: ...
    def post_review(self, repo: str, pr_number: str, summary: str, comments: list[dict]) -> str: ...


class GitHubBackend:
    def __init__(self, token: str, client: httpx.Client | None = None):
        if not token:
            raise ValueError("GITHUB_TOKEN is required for the github backend")
        self._client = client or httpx.Client(timeout=30)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get_pr_diff(self, repo: str, pr_number: str) -> str:
        r = self._client.get(
            f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}",
            headers={**self._headers, "Accept": "application/vnd.github.v3.diff"},
        )
        r.raise_for_status()
        return r.text

    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        r = self._client.get(
            f"{GITHUB_API}/repos/{repo}/contents/{path}",
            params={"ref": ref},
            headers={**self._headers, "Accept": "application/vnd.github.raw+json"},
        )
        r.raise_for_status()
        return r.text

    def post_review(self, repo: str, pr_number: str, summary: str, comments: list[dict]) -> str:
        payload = {
            "body": summary,
            "event": "COMMENT",
            "comments": [
                {"path": c["path"], "line": c["line"], "side": "RIGHT", "body": c["body"]}
                for c in comments
            ],
        }
        r = self._client.post(
            f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews",
            headers={**self._headers, "Accept": "application/vnd.github+json"},
            json=payload,
        )
        r.raise_for_status()
        return r.json().get("html_url", "posted")


class LocalBackend:
    """Reads `<dir>/<pr_number>.diff`; writes `<dir>/out/<pr_number>.review.json`."""

    def __init__(self, directory: str):
        self.dir = Path(directory)

    def _safe(self, name: str) -> Path:
        path = (self.dir / name).resolve()
        if not path.is_relative_to(self.dir.resolve()):
            raise ValueError("path escapes the local PR directory")
        return path

    def get_pr_diff(self, repo: str, pr_number: str) -> str:
        return self._safe(f"{pr_number}.diff").read_text(encoding="utf-8")

    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        return self._safe(path).read_text(encoding="utf-8")

    def post_review(self, repo: str, pr_number: str, summary: str, comments: list[dict]) -> str:
        out = self._safe(f"out/{pr_number}.review.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"summary": summary, "comments": comments}, indent=2), encoding="utf-8")
        return str(out)


def make_backend(settings: Settings) -> PRBackend:
    if settings.pr_backend == "local":
        return LocalBackend(settings.local_pr_dir)
    return GitHubBackend(settings.github_token)
