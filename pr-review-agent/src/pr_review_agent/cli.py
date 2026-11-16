"""Command line entry point.

    pr-review review --repo owner/name --pr 12
    pr-review review --local examples --pr demo --llm baseline --auto-approve
    pr-review tools
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os


def _review(args: argparse.Namespace) -> None:
    if args.local:
        os.environ["PR_BACKEND"] = "local"
        os.environ["LOCAL_PR_DIR"] = args.local
    if args.llm:
        os.environ["LLM_PROVIDER"] = args.llm

    from .service import ReviewService

    async def run() -> dict:
        service = ReviewService.from_settings()
        record = await service.start(args.repo, args.pr, auto_approve=args.auto_approve or None)
        if record["status"] == "pending_approval":
            print(record["summary"], "\n")
            answer = input("Post this review? [y/N] ").strip().lower()
            record = await service.decide(record["review_id"], answer == "y")
        return record

    print(json.dumps(asyncio.run(run()), indent=2))


def _tools(_: argparse.Namespace) -> None:
    from .tool_client import ToolClient

    print("\n".join(asyncio.run(ToolClient.stdio().list_tools())))


def main() -> None:
    parser = argparse.ArgumentParser(prog="pr-review")
    sub = parser.add_subparsers(required=True)

    review = sub.add_parser("review", help="review one pull request")
    review.add_argument("--repo", default="local/demo", help="owner/name")
    review.add_argument("--pr", required=True, help="PR number, or the .diff file name in --local mode")
    review.add_argument("--local", metavar="DIR", help="read <DIR>/<pr>.diff instead of calling GitHub")
    review.add_argument("--llm", choices=["anthropic", "baseline"])
    review.add_argument("--auto-approve", action="store_true")
    review.set_defaults(func=_review)

    tools = sub.add_parser("tools", help="list the tools exposed by the MCP server")
    tools.set_defaults(func=_tools)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
