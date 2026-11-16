"""Run the full pipeline over the seeded-defect set and score it.

    python eval/run_eval.py --llm baseline
    python eval/run_eval.py --llm anthropic        # needs ANTHROPIC_API_KEY

A finding is a true positive when it has the expected category, is in the
expected file and lands within LINE_TOLERANCE lines of the planted defect.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from eval.dataset import CASES, expected_lines, write_cases  # noqa: E402

LINE_TOLERANCE = 2


def score_case(expected: list[dict], findings: list[dict]) -> dict:
    """Greedy one-to-one matching of findings to planted defects."""
    unmatched = list(findings)
    tp = 0
    for exp in expected:
        for f in unmatched:
            if (f["file"] == exp["file"] and f["category"] == exp["category"]
                    and abs(f["line"] - exp["line"]) <= LINE_TOLERANCE):
                unmatched.remove(f)
                tp += 1
                break
    return {"tp": tp, "fn": len(expected) - tp, "fp": len(unmatched)}


def summarise(rows: list[dict]) -> dict:
    tp = sum(r["tp"] for r in rows)
    fn = sum(r["fn"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    clean = [r for r in rows if r["expected"] == 0]
    by_category = {}
    for category in ("bug", "security", "tests"):
        subset = [r for r in rows if r["category"] == category]
        total = sum(r["expected"] for r in subset)
        by_category[category] = {
            "defects": total,
            "caught": sum(r["tp"] for r in subset),
            "recall": round(sum(r["tp"] for r in subset) / total, 3) if total else None,
        }
    return {
        "cases": len(rows),
        "defects": tp + fn,
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "clean_cases": len(clean),
        "clean_cases_with_no_comments": sum(1 for r in clean if r["fp"] == 0),
        "by_category": by_category,
        "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        "avg_cost_usd": round(sum(r["cost_usd"] for r in rows) / len(rows), 5),
        "avg_latency_s": round(sum(r["latency_s"] for r in rows) / len(rows), 2),
        "dropped_by_guardrail": sum(r["dropped"] for r in rows),
    }


async def run(llm_name: str, only: str | None) -> dict:
    cases_dir = write_cases(ROOT / "eval" / "cases")
    os.environ.update(PR_BACKEND="local", LOCAL_PR_DIR=str(cases_dir), LLM_PROVIDER=llm_name,
                      MCP_TRANSPORT="inprocess", AUTO_APPROVE="true",
                      TRACE_FILE=str(ROOT / "traces" / f"eval_{llm_name}.jsonl"))
    from pr_review_agent.service import ReviewService

    service = ReviewService.from_settings()
    rows = []
    for case in CASES:
        if only and only not in case["id"]:
            continue
        expected = expected_lines(case)
        started = time.perf_counter()
        record = await service.start("eval/repo", case["id"])
        row = {
            "id": case["id"],
            "category": case["expect"][0][0] if case["expect"] else "clean",
            "expected": len(expected),
            **score_case(expected, record["findings"]),
            "cost_usd": record["cost_usd"],
            "latency_s": round(time.perf_counter() - started, 2),
            "dropped": record["dropped_by_guardrail"],
            "findings": [f"{f['category']}@{f['line']}: {f['title']}" for f in record["findings"]],
        }
        rows.append(row)
        print(f"{row['id']:<32} tp={row['tp']} fn={row['fn']} fp={row['fp']}")
    return {"llm": llm_name, "model": os.getenv("ANTHROPIC_MODEL") if llm_name == "anthropic" else None,
            "summary": summarise(rows), "cases": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", choices=["baseline", "anthropic"], default="baseline")
    parser.add_argument("--only", help="run only cases whose id contains this text")
    args = parser.parse_args()
    result = asyncio.run(run(args.llm, args.only))
    out = ROOT / "eval" / "results" / f"{args.llm}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\n" + json.dumps(result["summary"], indent=2))
    print(f"\nSaved to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
