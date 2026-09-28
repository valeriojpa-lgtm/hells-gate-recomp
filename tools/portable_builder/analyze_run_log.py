#!/usr/bin/env python3
"""Turn a Dante's Inferno runtime log into conservative preservation gate evidence."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

TU_RE = re.compile(
    r"XEX patch applied successfully: base version:\s*([0-9.]+),\s*"
    r"new version:\s*([0-9.]+)",
    re.I,
)
UNRESOLVED_PATTERNS = (
    re.compile(
        r"Call to (?:unresolved|invalid or unregistered) function at guest "
        r"address 0x([0-9A-Fa-f]{8})",
        re.I,
    ),
    re.compile(
        r"Unresolved (?:call|branch) from 0x[0-9A-Fa-f]{8} to "
        r"0x([0-9A-Fa-f]{8})",
        re.I,
    ),
)
SWAP_RE = re.compile(
    r"\[GPU SwapGuest\].*?ptr=0x([0-9A-Fa-f]+).*?bytes=(\d+).*?"
    r"nonzero=(\d+).*?hash=0x([0-9A-Fa-f]+)",
    re.I,
)
VDSWAP_RE = re.compile(r"\bVdSwap:.*?(\d+)x(\d+)", re.I)
VFETCH_RE = re.compile(r"\bVFETCH-OOB\b", re.I)
REGISTER_RE = re.compile(
    r"\bregistered\s+([0-9][0-9,._ ]*)\s+functions\b", re.I
)
FIBER_RE = re.compile(
    r"Q01 FIBER: cleared TU2 callback slot 0x82CE68E4", re.I
)
ACCESS_RE = re.compile(
    r"(?:Unhandled guest access violation|Access violation faulting PC|"
    r"EXCEPTION_ACCESS_VIOLATION)",
    re.I,
)
FATAL_RE = re.compile(
    r"(?:\[fatal\]|\bREX_FATAL\b|Assertion failed:|\bPANIC\b)", re.I
)

# Observations are deliberately not gate PASS criteria. They answer the much
# safer question "did this subsystem produce evidence in this run?"
OBSERVATION_PATTERNS = {
    "input_sdl": (
        re.compile(r"SDL input driver initialized successfully", re.I),
        re.compile(r"\binput_backend\b.*\bsdl\b", re.I),
    ),
    "audio_xma": (
        re.compile(r"\bXMA\b", re.I),
        re.compile(r"\bXAudio\b", re.I),
        re.compile(r"\bAPU\b", re.I),
    ),
    "video_vp6": (
        re.compile(r"\bVP6\b", re.I),
        re.compile(r"\[GPU VP6", re.I),
    ),
    "save_content": (
        re.compile(r"XamContentCreate(?:Ex|Internal)?", re.I),
        re.compile(r"XUserFindUsers", re.I),
    ),
    "language": (
        re.compile(r"\buser_language\b", re.I),
        re.compile(r"XamGetLanguage", re.I),
        re.compile(r"\bXLanguage\b", re.I),
    ),
    "dlc": (
        re.compile(r"DLC-MOD", re.I),
        re.compile(r"\bdlc_trace\b", re.I),
        re.compile(r"\.(?:dlm|lu2)\b", re.I),
    ),
    "shader": (
        re.compile(r"Initializing shader storage", re.I),
        re.compile(r"Translated\s+\d+\s+shaders", re.I),
        re.compile(r"shader[_ -]?cache", re.I),
    ),
}
FILESYSTEM_ERROR_PATTERNS = (
    re.compile(r"NtCreateFile.*FAILED", re.I),
    re.compile(r"0xC000000F", re.I),
    re.compile(r"(?:file|path).*(?:not found|missing)", re.I),
)


@dataclass
class Gate:
    id: str
    status: str
    summary: str
    evidence: list[str]


def unresolved_targets(data: str) -> Counter[int]:
    counts: Counter[int] = Counter()
    for line in data.splitlines():
        for pattern in UNRESOLVED_PATTERNS:
            match = pattern.search(line)
            if match:
                counts[int(match.group(1), 16)] += 1
                break
    return counts


def observation_counts(data: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, patterns in OBSERVATION_PATTERNS.items():
        matched_lines = 0
        for line in data.splitlines():
            if any(pattern.search(line) for pattern in patterns):
                matched_lines += 1
        counts[name] = matched_lines
    counts["filesystem_errors"] = sum(
        1
        for line in data.splitlines()
        if any(pattern.search(line) for pattern in FILESYSTEM_ERROR_PATTERNS)
    )
    return counts


def report(data: str) -> dict:
    tus = TU_RE.findall(data)
    tu_ok = any(a == "0.0.0.1" and b == "0.0.2.1" for a, b in tus)

    unresolved = unresolved_targets(data)
    total = sum(unresolved.values())

    swaps = [
        {
            "ptr": f"0x{int(match.group(1), 16):08X}",
            "bytes": int(match.group(2)),
            "nonzero": int(match.group(3)),
            "hash": "0x" + match.group(4).upper(),
        }
        for match in SWAP_RE.finditer(data)
    ]
    nonzero = [sample for sample in swaps if sample["nonzero"] > 0]
    vds = [(int(a), int(b)) for a, b in VDSWAP_RE.findall(data)]
    regs = [
        int(re.sub(r"[^0-9]", "", match.group(1)))
        for match in REGISTER_RE.finditer(data)
        if re.sub(r"[^0-9]", "", match.group(1))
    ]

    access_violations = len(ACCESS_RE.findall(data))
    fatal_markers = len(FATAL_RE.findall(data))
    observations = observation_counts(data)

    gates = [
        Gate(
            "GATE-0",
            "PASS" if tu_ok else "FAIL",
            "TU2 applied 0.0.0.1 -> 0.0.2.1"
            if tu_ok
            else "expected TU2 application was not proven",
            [f"{a} -> {b}" for a, b in tus[-5:]]
            or ["no XEX patch-success line"],
        )
    ]

    progress = bool(vds or swaps)
    if not progress:
        gate2_status = "INCONCLUSIVE"
        gate2_summary = (
            f"{total} unresolved dispatch(es); no renderer progress evidence"
            if total
            else "zero unresolved seen, but no renderer progress evidence"
        )
    elif total:
        gate2_status = "FAIL"
        gate2_summary = (
            f"{total} unresolved guest dispatch(es), "
            f"{len(unresolved)} unique target(s)"
        )
    else:
        gate2_status = "PASS"
        gate2_summary = "zero unresolved guest dispatches with renderer progress evidence"

    gate2_evidence = [
        f"0x{address:08X}: {count} call(s)"
        for address, count in unresolved.most_common()
    ] or ["no unresolved-dispatch lines found"]
    if regs:
        gate2_evidence.append(f"reported registered functions: {max(regs)}")
    gates.append(Gate("GATE-2", gate2_status, gate2_summary, gate2_evidence))

    if gate2_status != "PASS":
        gates.append(
            Gate(
                "GATE-3",
                "BLOCKED",
                "framebuffer gate blocked until GATE-2 passes",
                [
                    f"SwapGuest samples={len(swaps)}; "
                    f"non-zero={len(nonzero)}"
                ],
            )
        )
    elif nonzero:
        best = max(nonzero, key=lambda sample: sample["nonzero"])
        gates.append(
            Gate(
                "GATE-3",
                "PASS",
                f"guest framebuffer became non-zero "
                f"({best['nonzero']} sampled bytes)",
                [f"{best['ptr']} {best['hash']}"],
            )
        )
    elif swaps:
        gates.append(
            Gate(
                "GATE-3",
                "FAIL",
                f"all {len(swaps)} sampled guest framebuffers remained zero",
                [],
            )
        )
    else:
        gates.append(
            Gate(
                "GATE-3",
                "INCONCLUSIVE",
                "GATE-2 passed but no SwapGuest sample was logged",
                [],
            )
        )

    later_gates = (
        ("GATE-4", "intro/menu"),
        ("GATE-5", "input/menu navigation"),
        ("GATE-6", "New Game"),
        ("GATE-7", "first gameplay"),
        ("GATE-8", "audio/video sync"),
        ("GATE-9", "checkpoint/save/load"),
        ("GATE-10", "languages"),
        ("GATE-11", "campaign complete"),
        ("GATE-12", "TU2/DLC"),
        ("GATE-13", "PC modernization"),
    )
    for gate_id, label in later_gates:
        gates.append(
            Gate(
                gate_id,
                "UNVERIFIED",
                f"{label} requires later explicit evidence",
                [],
            )
        )

    diagnosis: list[str] = []
    if total:
        diagnosis.append(
            "PRIMARY: guest function coverage/dispatch. Do not attribute the "
            "black frame to VFETCH-OOB while GATE-2 is failing."
        )
    elif access_violations or fatal_markers:
        diagnosis.append(
            "PRIMARY: runtime fault evidence remains after guest dispatch "
            f"coverage ({access_violations} access-violation marker(s), "
            f"{fatal_markers} fatal/assert marker(s))."
        )
    elif progress and swaps and not nonzero:
        diagnosis.append(
            "PRIMARY NEXT: guest framebuffer is still zero after dispatch "
            "coverage passed; renderer/shader/resolve investigation is unlocked."
        )
    elif nonzero:
        diagnosis.append(
            "Framebuffer production is alive; any visual failure is downstream "
            "of guest framebuffer generation."
        )
    else:
        diagnosis.append(
            "Insufficient runtime progress evidence for subsystem attribution."
        )

    vfetch_count = len(VFETCH_RE.findall(data))
    if vfetch_count:
        diagnosis.append(
            f"SECONDARY: {vfetch_count} VFETCH-OOB warning(s); preserve as "
            "diagnostics until GATE-2 is PASS."
        )
    if not FIBER_RE.search(data):
        diagnosis.append(
            "TU2 fiber callback-clear marker not observed; fiber status is "
            "unproven for this RUN."
        )
    if observations["filesystem_errors"]:
        diagnosis.append(
            f"FILESYSTEM: {observations['filesystem_errors']} possible "
            "file/path failure line(s) observed."
        )

    observed_names = [
        name
        for name, count in observations.items()
        if count and name != "filesystem_errors"
    ]
    if observed_names:
        diagnosis.append(
            "OBSERVED ONLY (not gate PASS): " + ", ".join(observed_names) + "."
        )

    metrics = {
        "registered_functions": max(regs) if regs else None,
        "unresolved_dispatch_total": total,
        "unresolved_unique_targets": len(unresolved),
        "unresolved_targets": {
            f"0x{address:08X}": count
            for address, count in unresolved.most_common()
        },
        "fiber_callback_cleared": bool(FIBER_RE.search(data)),
        "vdswap_count": len(vds),
        "vdswap_sizes": sorted({f"{a}x{b}" for a, b in vds}),
        "swapguest_samples": len(swaps),
        "swapguest_nonzero_samples": len(nonzero),
        "vfetch_oob_count": vfetch_count,
        "access_violation_marker_count": access_violations,
        "fatal_assert_marker_count": fatal_markers,
        "observations": observations,
    }

    return {
        "schema": 2,
        "audit": "dantes-inferno-runtime-gates",
        "metrics": metrics,
        "gates": [asdict(gate) for gate in gates],
        "diagnosis": diagnosis,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--markdown", dest="md_path")
    args = parser.parse_args()

    path = Path(args.log)
    if not path.exists():
        print(f"ERROR: log not found: {path}")
        return 2

    result = report(path.read_text(encoding="utf-8", errors="replace"))

    for gate in result["gates"]:
        print(
            f"[{gate['status']:12}] {gate['id']:8} "
            f"{gate['summary']}"
        )
        for evidence in gate["evidence"]:
            print(f"               - {evidence}")

    observations = result["metrics"]["observations"]
    print("OBSERVATIONS:")
    for name, count in observations.items():
        print(f"  {name}: {count}")

    for line in result["diagnosis"]:
        print("DIAG:", line)

    if args.json_path:
        output = Path(args.json_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.md_path:
        output = Path(args.md_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Dante's Inferno RUN Gate Report",
            "",
            "| Gate | Status | Evidence summary |",
            "|---|---|---|",
        ]
        lines += [
            f"| `{gate['id']}` | **{gate['status']}** | "
            f"{gate['summary']} |"
            for gate in result["gates"]
        ]
        lines += [
            "",
            "## Subsystem observations",
            "",
            "These observations show that code paths/logging were reached. "
            "They are not functional PASS criteria.",
            "",
            "| Subsystem | Matching log lines |",
            "|---|---:|",
        ]
        lines += [
            f"| `{name}` | {count} |"
            for name, count in observations.items()
        ]
        lines += ["", "## Diagnosis", ""]
        lines += [f"- {line}" for line in result["diagnosis"]]
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return (
        1
        if any(
            gate["id"] in {"GATE-0", "GATE-2"}
            and gate["status"] == "FAIL"
            for gate in result["gates"]
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
