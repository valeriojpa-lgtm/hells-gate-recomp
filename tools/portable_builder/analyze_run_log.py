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
LEGACY_SWAP_RE = re.compile(
    r"\[GPU SwapGuest\].*?ptr=0x([0-9A-Fa-f]+).*?bytes=(\d+).*?"
    r"nonzero=(\d+).*?hash=0x([0-9A-Fa-f]+)",
    re.I,
)
GUEST_OUTPUT_CAPTURE_RE = re.compile(
    r"\[GPU GuestOutputCapture\]\s+frame=(\d+)\s+width=(\d+)\s+"
    r"height=(\d+)\s+stride=(\d+)\s+bytes=(\d+)\s+nonzero=(\d+)\s+"
    r"hash=0x([0-9A-Fa-f]+)",
    re.I,
)
GUEST_OUTPUT_CAPTURE_FAIL_RE = re.compile(
    r"\[GPU GuestOutputCapture\]\s+frame=(\d+)\s+capture_failed",
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
SAVE_CONTENT_RE = re.compile(
    r"XamContentCreate:\s+root='([^']*)'\s+saved=(\d+)\s+"
    r"type=0[xX]([0-9A-Fa-f]+)\s+file='([^']*)'\s+flags=0[xX]([0-9A-Fa-f]+)",
    re.I,
)
SAVE_RESULT_RE = re.compile(
    r"XamContentCreateEx:\s+sync result=0[xX]([0-9A-Fa-f]+)\s+disposition=(\d+)",
    re.I,
)
SAVE_CLOSE_RE = re.compile(
    r"XamContentClose:\s+root='([^']*)'\s+result=0[xX]([0-9A-Fa-f]+)",
    re.I,
)
DANTE_SAVE_LANGUAGE_RE = re.compile(r"\bDI1-([A-Za-z]{2})-", re.I)

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

HISTORICAL_TU2_BLACKSCREEN_TARGETS = {0x8236E3C0, 0x825D2C30}
XEXP_SIGNATURE_RE = re.compile(r"XEX patch signature hash doesn't match", re.I)
BASE_DLC_DISABLED_RE = re.compile(
    r"DLC disabled for base-campaign preservation run", re.I
)
DLC_MUTATION_RE = re.compile(
    r"(?:Installing DLC package|Mirrored DLC content directory|"
    r"DLC auto-install complete:.*(?:[1-9]\d*) new packages|"
    r"DLC auto-install complete:.*(?:[1-9]\d*) mirrored dirs)",
    re.I,
)
SHADER_CACHE_SEEDED_RE = re.compile(
    r"Seeded\s+([1-9]\d*)\s+shader cache file", re.I
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

    legacy_swaps = [
        {
            "ptr": f"0x{int(match.group(1), 16):08X}",
            "bytes": int(match.group(2)),
            "nonzero": int(match.group(3)),
            "hash": "0x" + match.group(4).upper(),
        }
        for match in LEGACY_SWAP_RE.finditer(data)
    ]
    captures = [
        {
            "frame": int(match.group(1)),
            "width": int(match.group(2)),
            "height": int(match.group(3)),
            "stride": int(match.group(4)),
            "bytes": int(match.group(5)),
            "nonzero": int(match.group(6)),
            "hash": "0x" + match.group(7).upper(),
        }
        for match in GUEST_OUTPUT_CAPTURE_RE.finditer(data)
    ]
    capture_failures = [
        int(match.group(1))
        for match in GUEST_OUTPUT_CAPTURE_FAIL_RE.finditer(data)
    ]
    capture_nonzero = [sample for sample in captures if sample["nonzero"] > 0]
    capture_max_frame = max((sample["frame"] for sample in captures), default=0)
    vds = [(int(a), int(b)) for a, b in VDSWAP_RE.findall(data)]
    regs = [
        int(re.sub(r"[^0-9]", "", match.group(1)))
        for match in REGISTER_RE.finditer(data)
        if re.sub(r"[^0-9]", "", match.group(1))
    ]

    access_violations = len(ACCESS_RE.findall(data))
    fatal_markers = len(FATAL_RE.findall(data))
    observations = observation_counts(data)

    base_dlc_disabled = bool(BASE_DLC_DISABLED_RE.search(data))
    dlc_mutation_lines = [
        line for line in data.splitlines() if DLC_MUTATION_RE.search(line)
    ]
    shader_cache_seed_counts = [
        int(match.group(1)) for match in SHADER_CACHE_SEEDED_RE.finditer(data)
    ]
    shader_cache_seeded = sum(shader_cache_seed_counts)
    baseline_contamination = bool(
        (base_dlc_disabled and dlc_mutation_lines) or shader_cache_seeded
    )

    save_events = [
        {
            "root": match.group(1),
            "saved": match.group(2) == "1",
            "content_type": f"0x{int(match.group(3), 16):X}",
            "file": match.group(4),
            "flags": f"0x{int(match.group(5), 16):X}",
        }
        for match in SAVE_CONTENT_RE.finditer(data)
    ]
    save_results = [
        {
            "result": f"0x{int(match.group(1), 16):X}",
            "disposition": int(match.group(2)),
        }
        for match in SAVE_RESULT_RE.finditer(data)
    ]
    save_closes = [
        {
            "root": match.group(1),
            "result": f"0x{int(match.group(2), 16):X}",
        }
        for match in SAVE_CLOSE_RE.finditer(data)
    ]
    savedata_files = sorted({
        event["file"] for event in save_events if event["saved"] and event["file"]
    })
    save_language_codes = sorted({
        language.upper()
        for filename in savedata_files
        for language in DANTE_SAVE_LANGUAGE_RE.findall(filename)
    })

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

    progress = bool(vds or captures or legacy_swaps)
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
                "presenter-output gate blocked until GATE-2 passes",
                [
                    f"guest-output captures={len(captures)}; "
                    f"non-zero={len(capture_nonzero)}; "
                    f"legacy SwapGuest samples={len(legacy_swaps)}"
                ],
            )
        )
    elif capture_nonzero:
        best = max(capture_nonzero, key=lambda sample: sample["nonzero"])
        gates.append(
            Gate(
                "GATE-3",
                "PASS",
                f"actual D3D12 guest output became non-zero at frame "
                f"{best['frame']} ({best['nonzero']} non-zero bytes)",
                [
                    f"{best['width']}x{best['height']} stride={best['stride']} "
                    f"{best['hash']}"
                ],
            )
        )
    elif captures and capture_max_frame >= 512:
        gates.append(
            Gate(
                "GATE-3",
                "FAIL",
                f"actual D3D12 guest output remained zero through capture "
                f"frame {capture_max_frame}",
                [f"captures={len(captures)}; failures={len(capture_failures)}"],
            )
        )
    elif captures:
        gates.append(
            Gate(
                "GATE-3",
                "INCONCLUSIVE",
                f"actual guest output is zero in {len(captures)} early capture(s), "
                f"latest frame={capture_max_frame}; diagnostic horizon is frame 512",
                [f"capture failures={len(capture_failures)}"],
            )
        )
    else:
        gates.append(
            Gate(
                "GATE-3",
                "INCONCLUSIVE",
                "GATE-2 passed but no authoritative GuestOutputCapture sample was logged",
                [
                    "legacy SwapGuest memory samples are non-authoritative for "
                    "D3D12 presentation"
                ] if legacy_swaps else [],
            )
        )

    purity_evidence: list[str] = []
    if base_dlc_disabled:
        purity_evidence.append("base-campaign DLC-disabled marker observed")
    if dlc_mutation_lines:
        purity_evidence.extend(
            f"DLC activity: {line.strip()}" for line in dlc_mutation_lines[:8]
        )
    if shader_cache_seeded:
        purity_evidence.append(
            f"external/bundled shader cache seeded {shader_cache_seeded} file(s)"
        )
    gates.append(
        Gate(
            "BASELINE-PURITY",
            "FAIL" if baseline_contamination else (
                "PASS" if base_dlc_disabled else "UNVERIFIED"
            ),
            (
                "base-campaign run contains DLC/cache contamination"
                if baseline_contamination
                else "base-campaign DLC isolation observed"
                if base_dlc_disabled
                else "baseline purity marker was not observed"
            ),
            purity_evidence,
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
    elif capture_nonzero:
        diagnosis.append(
            "Actual presenter output is non-zero; any remaining black-screen "
            "symptom is downstream of guest-output generation/presentation."
        )
    elif captures and capture_max_frame >= 512:
        diagnosis.append(
            "PRIMARY NEXT: authoritative D3D12 presenter output remained zero "
            "through the diagnostic horizon; renderer/shader/resolve investigation "
            "is unlocked."
        )
    elif captures:
        diagnosis.append(
            "Authoritative presenter captures are still zero, but the diagnostic "
            "horizon has not been reached; do not promote this to renderer failure yet."
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
    if baseline_contamination:
        diagnosis.append(
            "BASELINE CONTAMINATION: this run is not a clean base-campaign "
            "reference because DLC activity and/or shader-cache seeding was "
            "observed despite the preservation baseline policy."
        )
    if legacy_swaps:
        diagnosis.append(
            "LEGACY RENDER DIAGNOSTIC: SwapGuest sampled raw guest memory that "
            "D3D12 IssueSwap does not use as the authoritative presentation source; "
            "those samples are retained for history only."
        )
    if capture_failures:
        diagnosis.append(
            f"RENDER CAPTURE: {len(capture_failures)} authoritative guest-output "
            "capture attempt(s) failed."
        )
    if savedata_files:
        diagnosis.append(
            "SAVE OBSERVED: " + ", ".join(savedata_files[:8])
            + (" ..." if len(savedata_files) > 8 else "")
        )
    if save_language_codes:
        diagnosis.append(
            "SAVE/LANGUAGE: Dante language-coded save filename(s) observed for "
            + ", ".join(save_language_codes)
            + ". Upstream explicitly reverted its destructive filename "
              "normalization, so cross-language visibility must be validated "
              "without mutating savedata in place."
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

    historical_matches: list[dict[str, str]] = []
    if HISTORICAL_TU2_BLACKSCREEN_TARGETS.intersection(unresolved):
        historical_matches.append(
            {
                "id": "upstream-v0.6.3-v0.6.4-tu2-black-screen",
                "confidence": "high",
                "reason": (
                    "RUN hit one or both TU2 indirect targets 0x8236E3C0 / "
                    "0x825D2C30 that upstream explicitly restored before the "
                    "v0.6.4 black-screen fix."
                ),
            }
        )
    if XEXP_SIGNATURE_RE.search(data):
        historical_matches.append(
            {
                "id": "upstream-issue-51-xexp-signature-mismatch",
                "confidence": "high",
                "reason": (
                    "Log contains the same XEX/XEXP patch signature mismatch "
                    "class reported in upstream issue #51."
                ),
            }
        )
    if access_violations and observations["save_content"]:
        historical_matches.append(
            {
                "id": "upstream-save-fiber-crash-family",
                "confidence": "medium",
                "reason": (
                    "Access-violation evidence occurred in a run that reached "
                    "save/content paths; upstream v0.6.4 fixed a save/fiber "
                    "crash family with full setjmp/longjmp restoration."
                ),
            }
        )
    if observations["video_vp6"] and observations["filesystem_errors"] == 0:
        historical_matches.append(
            {
                "id": "upstream-vp6-fmv-family",
                "confidence": "low",
                "reason": (
                    "VP6 paths were observed. This is only a routing hint for "
                    "the historical FMV artifact family, not evidence of a bug."
                ),
            }
        )
    if save_language_codes:
        historical_matches.append(
            {
                "id": "upstream-save-language-filename-family",
                "confidence": "high",
                "reason": (
                    "Dante save filenames contain a two-letter language code. "
                    "Upstream briefly normalized these names, then explicitly "
                    "reverted that mutation before v0.6.5."
                ),
            }
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
        "guest_output_capture_samples": len(captures),
        "guest_output_capture_nonzero_samples": len(capture_nonzero),
        "guest_output_capture_max_frame": capture_max_frame,
        "guest_output_capture_failures": capture_failures,
        "legacy_swapguest_samples": len(legacy_swaps),
        "legacy_swapguest_nonzero_samples": sum(
            1 for sample in legacy_swaps if sample["nonzero"] > 0
        ),
        "vfetch_oob_count": vfetch_count,
        "access_violation_marker_count": access_violations,
        "fatal_assert_marker_count": fatal_markers,
        "base_dlc_disabled_marker": base_dlc_disabled,
        "dlc_mutation_lines": dlc_mutation_lines,
        "shader_cache_seeded_files": shader_cache_seeded,
        "baseline_contamination": baseline_contamination,
        "save_content_events": save_events,
        "save_content_results": save_results,
        "save_content_closes": save_closes,
        "savedata_files": savedata_files,
        "save_language_codes": save_language_codes,
        "observations": observations,
    }

    return {
        "schema": 5,
        "audit": "dantes-inferno-runtime-gates",
        "metrics": metrics,
        "gates": [asdict(gate) for gate in gates],
        "diagnosis": diagnosis,
        "historical_matches": historical_matches,
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

    for match in result["historical_matches"]:
        print(
            "HIST:",
            match["id"],
            f"({match['confidence']})",
            match["reason"],
        )

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
        lines += ["", "## Historical signature matches", ""]
        if result["historical_matches"]:
            lines += [
                f"- **{match['id']}** ({match['confidence']}): {match['reason']}"
                for match in result["historical_matches"]
            ]
        else:
            lines += ["- None detected."]
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
