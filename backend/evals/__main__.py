"""CLI: python -m backend.evals [--subset smoke] [--baseline PATH] [--no-cache] [--topics ID,ID].

Runs the agent over the dataset, scores each topic, writes JSON + Markdown to
results/, and prints the Markdown summary to stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
from pathlib import Path

from dotenv import load_dotenv

# tools/search.py reads TAVILY_API_KEY into a module-level constant at import
# time, so .env has to be loaded before the runner import chain below.
load_dotenv("backend/.env")

import anthropic  # noqa: E402
import yaml  # noqa: E402

from . import report  # noqa: E402
from .graders.judge import JUDGE_MODEL  # noqa: E402
from .runner import run_topic  # noqa: E402

HERE = Path(__file__).parent
DATASET_PATH = HERE / "dataset.yaml"
RESULTS_DIR = HERE / "results"

# Matches the models the agent itself uses. If the agent routes per-phase in
# the future, this list will need to expand.
SYNTH_MODEL = "claude-sonnet-4-20250514"
DRAFT_MODEL = "claude-sonnet-4-20250514"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m backend.evals")
    p.add_argument(
        "--subset",
        choices=["smoke"],
        help="Run a small subset (smoke = first 3 topics).",
    )
    p.add_argument(
        "--topics",
        help="Comma-separated dataset IDs to run (overrides --subset).",
    )
    p.add_argument(
        "--baseline",
        type=Path,
        help="Path to a prior run JSON. Adds a diff section to the report.",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip the URL read cache (always re-fetch source content).",
    )
    return p.parse_args()


def _select_topics(dataset: list[dict], args: argparse.Namespace) -> list[dict]:
    if args.topics:
        wanted = {s.strip() for s in args.topics.split(",") if s.strip()}
        selected = [e for e in dataset if e["id"] in wanted]
        missing = wanted - {e["id"] for e in selected}
        if missing:
            raise SystemExit(f"Unknown topic ids: {sorted(missing)}")
        return selected
    if args.subset == "smoke":
        return dataset[:3]
    return dataset


async def _run(args: argparse.Namespace) -> int:
    dataset = yaml.safe_load(DATASET_PATH.read_text(encoding="utf-8"))
    entries = _select_topics(dataset, args)

    judge_client = anthropic.AsyncAnthropic()

    print(
        f"Running {len(entries)} topic(s); "
        f"cache={'off' if args.no_cache else 'on'}"
    )

    topic_runs: list[dict] = []
    for i, entry in enumerate(entries, 1):
        print(f"  [{i}/{len(entries)}] {entry['id']} ({entry['kind']}) ...", flush=True)
        try:
            run = await run_topic(
                entry, use_cache=not args.no_cache, judge_client=judge_client
            )
        except Exception as e:
            run = {
                "id": entry["id"],
                "topic": entry["topic"],
                "kind": entry["kind"],
                "error": f"{type(e).__name__}: {e}",
                "draft": "",
                "sources": [],
                "deterministic": {"structure_score": 0.0},
                "invariants": [],
                "judge": {"composite": 0, "rationale": "runner crashed",
                          "faithfulness": 0, "specificity": 0, "coverage": 0,
                          "citation_quality": 0, "cost_usd": 0.0},
                "cost_usd": 0.0,
                "duration_s": 0.0,
                "phase_timings": {},
            }
        print(
            f"      composite={run['judge']['composite']}  "
            f"structure={'✓' if run['deterministic'].get('structure_score') else '✗'}  "
            f"cost=${run['cost_usd']:.4f}  t={run['duration_s']}s"
        )
        topic_runs.append(run)

    timestamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    record = report.build_run_record(
        topics=topic_runs,
        models={
            "synthesize": SYNTH_MODEL,
            "draft": DRAFT_MODEL,
            "judge": JUDGE_MODEL,
        },
        timestamp=timestamp,
    )

    baseline = report.load_baseline(args.baseline) if args.baseline else None

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"run-{timestamp}.json"
    md_path = RESULTS_DIR / f"run-{timestamp}.md"
    report.write_json(record, json_path)
    report.write_markdown(record, md_path, baseline=baseline)

    print()
    print(md_path.read_text(encoding="utf-8"))
    print(f"\nJSON:     {json_path}")
    print(f"Markdown: {md_path}")
    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
