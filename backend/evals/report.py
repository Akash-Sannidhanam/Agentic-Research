"""Serialize eval runs to JSON + Markdown, and diff against a baseline run."""

from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path
from typing import Any

REGRESSION_THRESHOLD = 0.5  # judge dimension drop flagged as regression


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _aggregate(topics: list[dict]) -> dict:
    if not topics:
        return {}
    scored = [t for t in topics if "error" not in t]
    composites = [t["judge"]["composite"] for t in scored]
    coverages = [t["deterministic"].get("citation_coverage", 0) for t in scored]
    structure_passes = [t["deterministic"]["structure_score"] for t in scored]
    costs = [t["cost_usd"] for t in topics]
    durations = [t["duration_s"] for t in topics]

    hitl_invariants = [
        inv for t in scored if t["kind"] == "hitl" for inv in t["invariants"]
    ]
    hitl_pass = (
        sum(1 for inv in hitl_invariants if inv["pass"]) / len(hitl_invariants)
        if hitl_invariants
        else None
    )

    return {
        "n_topics": len(topics),
        "n_errored": len(topics) - len(scored),
        "composite_mean": round(statistics.fmean(composites), 2) if composites else 0,
        "faithfulness_mean": round(
            statistics.fmean(t["judge"]["faithfulness"] for t in scored), 2
        ) if scored else 0,
        "specificity_mean": round(
            statistics.fmean(t["judge"]["specificity"] for t in scored), 2
        ) if scored else 0,
        "coverage_mean": round(
            statistics.fmean(t["judge"]["coverage"] for t in scored), 2
        ) if scored else 0,
        "citation_quality_mean": round(
            statistics.fmean(t["judge"]["citation_quality"] for t in scored), 2
        ) if scored else 0,
        "citation_coverage_mean": round(statistics.fmean(coverages), 2) if coverages else 0,
        "structure_pass_rate": round(statistics.fmean(structure_passes), 2) if structure_passes else 0,
        "hitl_invariant_pass_rate": (
            round(hitl_pass, 2) if hitl_pass is not None else None
        ),
        "total_cost_usd": round(sum(costs), 4),
        "mean_cost_usd": round(statistics.fmean(costs), 4) if costs else 0,
        "total_duration_s": round(sum(durations), 1),
    }


def build_run_record(
    topics: list[dict], models: dict, timestamp: str
) -> dict:
    return {
        "timestamp": timestamp,
        "git_commit": _git_commit(),
        "models": models,
        "aggregate": _aggregate(topics),
        "topics": topics,
    }


def write_json(record: dict, path: Path) -> None:
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


# ---------- Markdown rendering ----------

def _aggregate_table(agg: dict) -> str:
    rows = [
        ("Topics", agg["n_topics"]),
        ("Errored", agg["n_errored"]),
        ("Composite (judge mean)", agg["composite_mean"]),
        ("Faithfulness", agg["faithfulness_mean"]),
        ("Specificity", agg["specificity_mean"]),
        ("Coverage", agg["coverage_mean"]),
        ("Citation quality", agg["citation_quality_mean"]),
        ("Citation coverage (det.)", agg["citation_coverage_mean"]),
        ("Structure pass rate", agg["structure_pass_rate"]),
    ]
    if agg.get("hitl_invariant_pass_rate") is not None:
        rows.append(("HITL invariant pass rate", agg["hitl_invariant_pass_rate"]))
    rows.extend([
        ("Total cost (USD)", f"${agg['total_cost_usd']:.4f}"),
        ("Mean cost per topic (USD)", f"${agg['mean_cost_usd']:.4f}"),
        ("Total duration (s)", agg["total_duration_s"]),
    ])
    out = ["| Metric | Value |", "|---|---|"]
    out.extend(f"| {k} | {v} |" for k, v in rows)
    return "\n".join(out)


def _topic_row(t: dict) -> str:
    if "error" in t:
        return (
            f"| `{t['id']}` | {t['kind']} | ERROR | — | — | — | "
            f"${t['cost_usd']:.4f} | {t['duration_s']}s |"
        )
    j = t["judge"]
    d = t["deterministic"]
    inv_summary = ""
    if t["invariants"]:
        passes = sum(1 for i in t["invariants"] if i["pass"])
        inv_summary = f" ({passes}/{len(t['invariants'])})"
    return (
        f"| `{t['id']}` | {t['kind']}{inv_summary} | "
        f"{j['composite']} | {j['faithfulness']}/{j['specificity']}/"
        f"{j['coverage']}/{j['citation_quality']} | "
        f"{d['citation_coverage']} | "
        f"{'✓' if d['structure_score'] else '✗'} | "
        f"${t['cost_usd']:.4f} | {t['duration_s']}s |"
    )


def _topic_details(t: dict) -> str:
    if "error" in t:
        return f"### `{t['id']}`\n\n**Error:** `{t['error']}`\n"
    lines = [f"### `{t['id']}` — {t['topic']}", ""]
    lines.append(f"- **Judge rationale:** {t['judge']['rationale']}")
    det = t["deterministic"]
    lines.append(
        f"- **Structure:** exec_summary={det['has_exec_summary']}, "
        f"sections={det['section_count']}, "
        f"key_takeaways={det['key_takeaways_count']}, "
        f"hallucinated_urls={det['hallucinated_urls']}"
    )
    if t["invariants"]:
        for inv in t["invariants"]:
            status = "✓" if inv["pass"] else "✗"
            lines.append(f"- **Invariant** `{inv['name']}`: {status} — {inv['detail']}")
    lines.append(
        f"- **Phase timings:** "
        + ", ".join(f"{k}={v}s" for k, v in t["phase_timings"].items())
    )
    return "\n".join(lines) + "\n"


def render_markdown(record: dict, baseline: dict | None = None) -> str:
    agg = record["aggregate"]
    out = [
        f"# Eval Run — {record['timestamp']}",
        "",
        f"**Commit:** `{record['git_commit']}`  ",
        f"**Models:** synthesize=`{record['models']['synthesize']}`, "
        f"draft=`{record['models']['draft']}`, "
        f"judge=`{record['models']['judge']}`",
        "",
        "## Aggregate",
        "",
        _aggregate_table(agg),
        "",
        "## Per-topic",
        "",
        "| ID | Kind | Composite | F/S/C/CQ | Cite cov | Struct | Cost | Time |",
        "|---|---|---|---|---|---|---|---|",
    ]
    out.extend(_topic_row(t) for t in record["topics"])
    out.extend(["", "<details><summary>Topic details</summary>", ""])
    out.extend(_topic_details(t) for t in record["topics"])
    out.append("</details>")

    if baseline is not None:
        out.append("")
        out.append(_render_diff(record, baseline))

    return "\n".join(out) + "\n"


def _render_diff(current: dict, baseline: dict) -> str:
    out = [
        f"## Diff vs baseline (`{baseline['timestamp']}`, commit `{baseline['git_commit']}`)",
        "",
    ]
    cur_agg = current["aggregate"]
    base_agg = baseline["aggregate"]

    def fmt_delta(a, b):
        delta = a - b
        sign = "+" if delta > 0 else ""
        return f"{sign}{delta:.2f}"

    rows = [
        ("Composite", cur_agg["composite_mean"], base_agg["composite_mean"]),
        ("Faithfulness", cur_agg["faithfulness_mean"], base_agg["faithfulness_mean"]),
        ("Specificity", cur_agg["specificity_mean"], base_agg["specificity_mean"]),
        ("Coverage", cur_agg["coverage_mean"], base_agg["coverage_mean"]),
        ("Citation quality", cur_agg["citation_quality_mean"], base_agg["citation_quality_mean"]),
        ("Citation coverage", cur_agg["citation_coverage_mean"], base_agg["citation_coverage_mean"]),
        ("Structure pass rate", cur_agg["structure_pass_rate"], base_agg["structure_pass_rate"]),
        ("Total cost (USD)", cur_agg["total_cost_usd"], base_agg["total_cost_usd"]),
    ]
    out.append("| Metric | Baseline | Current | Δ |")
    out.append("|---|---|---|---|")
    for name, cur, base in rows:
        out.append(f"| {name} | {base} | {cur} | {fmt_delta(cur, base)} |")

    # Per-topic regressions
    base_topics = {t["id"]: t for t in baseline["topics"]}
    regressions = []
    for t in current["topics"]:
        if "error" in t or t["id"] not in base_topics:
            continue
        bt = base_topics[t["id"]]
        if "error" in bt:
            continue
        for dim in ("faithfulness", "specificity", "coverage", "citation_quality"):
            delta = t["judge"][dim] - bt["judge"][dim]
            if delta <= -REGRESSION_THRESHOLD:
                regressions.append(
                    f"- `{t['id']}` **{dim}** dropped {delta:+.1f} "
                    f"({bt['judge'][dim]} → {t['judge'][dim]})"
                )

    out.append("")
    if regressions:
        out.append("### ⚠️  Regressions (dimension drop ≥ 0.5)")
        out.append("")
        out.extend(regressions)
    else:
        out.append("### No per-topic regressions detected.")

    return "\n".join(out)


def write_markdown(record: dict, path: Path, baseline: dict | None = None) -> None:
    path.write_text(render_markdown(record, baseline), encoding="utf-8")


def load_baseline(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
