"""FastAPI service: GitHub webhook in, approval endpoints for the human reviewer.

Run with: uvicorn pr_review_agent.app:app --port 8000
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from .config import load_settings
from .service import ReviewService

log = logging.getLogger("pr_review_agent")


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Check GitHub's X-Hub-Signature-256 header (HMAC-SHA256 of the raw body)."""
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_app(service: ReviewService | None = None, webhook_secret: str | None = None) -> FastAPI:
    settings = load_settings()
    secret = settings.webhook_secret if webhook_secret is None else webhook_secret
    app = FastAPI(title="PR Review Agent", version="0.1.0")
    holder: dict[str, ReviewService] = {}

    def svc() -> ReviewService:
        if "s" not in holder:
            holder["s"] = service or ReviewService.from_settings(settings)
        return holder["s"]

    async def run_review(repo: str, pr_number: str) -> None:
        try:
            record = await svc().start(repo, pr_number)
            log.info("review %s for %s#%s: %s", record["review_id"], repo, pr_number, record["status"])
        except Exception:
            log.exception("review failed for %s#%s", repo, pr_number)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/webhook", status_code=202)
    async def webhook(request: Request, background: BackgroundTasks,
                      x_github_event: str | None = Header(default=None),
                      x_hub_signature_256: str | None = Header(default=None)) -> dict:
        body = await request.body()
        if not verify_signature(secret, body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="invalid signature")
        if x_github_event != "pull_request":
            return {"ignored": x_github_event}
        payload = json.loads(body)
        if payload.get("action") not in {"opened", "synchronize", "reopened"}:
            return {"ignored": payload.get("action")}
        repo = payload["repository"]["full_name"]
        pr_number = str(payload["pull_request"]["number"])
        background.add_task(run_review, repo, pr_number)
        return {"accepted": f"{repo}#{pr_number}"}

    @app.get("/reviews")
    def list_reviews(status: str | None = None) -> list[dict]:
        records = list(svc().reviews.values())
        return [r for r in records if status is None or r["status"] == status]

    @app.get("/reviews/{review_id}")
    def get_review(review_id: str) -> dict:
        record = svc().reviews.get(review_id)
        if record is None:
            raise HTTPException(status_code=404, detail="review not found")
        return record

    async def _decide(review_id: str, approved: bool) -> dict:
        try:
            return await svc().decide(review_id, approved)
        except KeyError:
            raise HTTPException(status_code=404, detail="review not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/reviews/{review_id}/approve")
    async def approve(review_id: str) -> dict:
        return await _decide(review_id, True)

    @app.post("/reviews/{review_id}/reject")
    async def reject(review_id: str) -> dict:
        return await _decide(review_id, False)

    return app


app = create_app()
