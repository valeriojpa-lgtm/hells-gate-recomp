#!/usr/bin/env python3
"""Compare a current Dante preservation RUN report against a sanitized baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def gate_map(report: dict) -> dict[str, str]:
    return {
        item.get("id", ""): item.get("status", "UNKNOWN")
        for item in report.get("gates", [])
        if item.get("id")
    }


def compare_reports(baseline: dict, current: dict) -> dict:
    before = baseline.get("metrics", {})
    after = current.get("metrics", {})
    before_gates = baseline.get("gates", {})
    after_gates = gate_map(current)

    before_targets = {
        key: int(value)
        for key, value in (before.get("unresolved_targets") or {}).items()
    }
    after_targets = {
        key: int(value)
        for key, value in (after.get("unresolved_targets") or {}).items()
    }

    all_targets = sorted(set(before_targets) | set(after_targets))
    target_delta = {
        target: {
            "before": before_targets.get(target, 0),
            "after": after_targets.get(target, 0),
            "delta": after_targets.get(target, 0) - before_targets.get(target, 0),
        }
        for target in all_targets
    }

    findings: list[dict[str, str]] = []

    old_g2 = before_gates.get("GATE-2", "UNKNOWN")
    new_g2 = after_gates.get("GATE-2", "UNKNOWN")
    if old_g2 == "FAIL" and new_g2 == "PASS":
        findings.append({
            "level": "major_progress",
            "text": "GATE 2 changed from FAIL to PASS: the historical unresolved-dispatch blocker is eliminated in this run.",
        })
    elif new_g2 == "FAIL":
        findings.append({
            "level": "blocker",
            "text": "GATE 2 is still FAIL; guest function coverage remains the primary blocker.",
        })
    elif new_g2 == "INCONCLUSIVE":
        findings.append({
            "level": "blocked",
            "text": "GATE 2 is inconclusive because the run did not provide enough runtime progress evidence.",
        })

    before_total = int(before.get("unresolved_dispatch_total") or 0)
    after_total = int(after.get("unresolved_dispatch_total") or 0)
    findings.append({
        "level": "metric",
        "text": f"Unresolved guest dispatches: {before_total} -> {after_total}.",
    })

    eliminated = [
        target for target, values in target_delta.items()
        if values["before"] > 0 and values["after"] == 0
    ]
    introduced = [
        target for target, values in target_delta.items()
        if values["before"] == 0 and values["after"] > 0
    ]
    if eliminated:
        findings.append({
            "level": "progress",
            "text": "Historical unresolved targets eliminated: " + ", ".join(eliminated) + ".",
        })
    if introduced:
        findings.append({
            "level": "regression",
            "text": "New unresolved targets appeared: " + ", ".join(introduced) + ".",
        })

    old_g3 = before_gates.get("GATE-3", "UNKNOWN")
    new_g3 = after_gates.get("GATE-3", "UNKNOWN")
    findings.append({
        "level": "metric",
        "text": f"GATE 3: {old_g3} -> {new_g3}.",
    })
    if old_g3 == "BLOCKED" and new_g3 in {"PASS", "FAIL", "INCONCLUSIVE"} and new_g2 == "PASS":
        findings.append({
            "level": "progress",
            "text": "Renderer output diagnosis is unlocked because GATE 2 passed.",
        })

    before_reg = before.get("registered_functions")
    after_reg = after.get("registered_functions")
    if before_reg is not None and after_reg is not None:
        findings.append({
            "level": "metric",
            "text": f"Registered recompiled functions: {before_reg} -> {after_reg}.",
        })

    before_vfetch = int(before.get("vfetch_oob_count") or 0)
    after_vfetch = int(after.get("vfetch_oob_count") or 0)
    findings.append({
        "level": "metric",
        "text": f"VFETCH-OOB diagnostics: {before_vfetch} -> {after_vfetch}; this is secondary unless GATE 2 is PASS.",
    })

    before_fiber = bool(before.get("fiber_callback_cleared"))
    after_fiber = bool(after.get("fiber_callback_cleared"))
    if before_fiber and not after_fiber:
        findings.append({
            "level": "regression",
            "text": "TU2 fiber callback-clear evidence disappeared.",
        })
    elif after_fiber:
        findings.append({
            "level": "stable",
            "text": "TU2 fiber callback-clear evidence remains present.",
        })

    obs = after.get("observations") or {}
    optional_after = int(obs.get("optional_viv_probe_misses") or 0)
    fs_after = int(obs.get("filesystem_errors") or 0)
    findings.append({
        "level": "metric",
        "text": f"Filesystem: optional BIGFILE2-12 probes={optional_after}; real error lines={fs_after}.",
    })

    if after.get("baseline_contamination"):
        findings.append({
            "level": "regression",
            "text": "Current run is contaminated by DLC activity and/or shader-cache seeding.",
        })

    return {
        "schema": 1,
        "baseline_id": baseline.get("id", "unknown"),
        "current_report_schema": current.get("schema"),
        "gate_delta": {
            key: {
                "before": before_gates.get(key, "UNKNOWN"),
                "after": after_gates.get(key, "UNKNOWN"),
            }
            for key in sorted(set(before_gates) | set(after_gates))
            if key.startswith("GATE-")
        },
        "unresolved_target_delta": target_delta,
        "findings": findings,
    }


def write_markdown(result: dict, path: Path) -> None:
    lines = [
        "# RUN delta vs historical RUN00(5)",
        "",
        f"Baseline: `{result['baseline_id']}`",
        "",
        "## Findings",
        "",
    ]
    for finding in result["findings"]:
        lines.append(f"- **{finding['level']}** — {finding['text']}")

    lines += [
        "",
        "## Gate delta",
        "",
        "| Gate | Before | After |",
        "|---|---|---|",
    ]
    for gate_id, delta in result["gate_delta"].items():
        lines.append(
            f"| `{gate_id}` | {delta['before']} | {delta['after']} |"
        )

    lines += [
        "",
        "## Unresolved target delta",
        "",
        "| Target | Before | After | Delta |",
        "|---|---:|---:|---:|",
    ]
    for target, delta in result["unresolved_target_delta"].items():
        lines.append(
            f"| `{target}` | {delta['before']} | {delta['after']} | {delta['delta']:+d} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("current_report")
    parser.add_argument(
        "--baseline",
        default=str(Path(__file__).with_name("run005_baseline.json")),
    )
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--markdown", dest="md_path")
    args = parser.parse_args()

    current = json.loads(Path(args.current_report).read_text(encoding="utf-8-sig"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8-sig"))
    result = compare_reports(baseline, current)

    for finding in result["findings"]:
        print(f"DELTA [{finding['level']}]: {finding['text']}")

    if args.json_path:
        out = Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.md_path:
        out = Path(args.md_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        write_markdown(result, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
