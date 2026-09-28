#!/usr/bin/env python3
"""Preservation-oriented adaptive manifest helper for Dante's Inferno.

The manifest is cumulative by design. A reset keeps every upstream entrypoint
that has already been proven necessary for indirect dispatch, preserves
upstream non-function metadata that codegen depends on, and then layers
runtime-learned targets on top. Static closure may add more direct targets, but
it never replaces the preserved knowledge base.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFEST = os.path.join(ROOT, "dantes_inferno_manifest.toml")
GEN_DIR = os.path.join(ROOT, "generated", "default")
SEED_FILE = os.path.join(os.path.dirname(__file__), "upstream_function_seeds.txt")
RUNTIME_SEEDS = os.path.join(os.path.dirname(__file__), "runtime_function_seeds.txt")

CANONICAL_MANIFEST = os.path.join(
    os.path.dirname(__file__), "upstream_manifest_base.toml"
)


ENTRY_RE = re.compile(r"^\[entrypoint\.functions\.0x([0-9A-Fa-f]+)\]$", re.M)
CALL_RE = re.compile(
    r'REX_FATAL\("Unresolved call from 0x[0-9A-Fa-f]+ to 0x([0-9A-Fa-f]+)"\)'
)
BRANCH_RE = re.compile(
    r'REX_FATAL\("Unresolved branch from 0x[0-9A-Fa-f]+ to 0x([0-9A-Fa-f]+)"\)'
)
RUNTIME_TARGET_RES = (
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


def is_guest_code_address(addr: int) -> bool:
    return 0x82000000 <= addr < 0x83000000


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def read_seed_file(path: str) -> set[int]:
    if not os.path.exists(path):
        return set()
    seeds: set[int] = set()
    for raw in read_text(path).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            addr = int(line, 0)
        except ValueError as exc:
            raise SystemExit(f"Invalid seed address in {path}: {line}") from exc
        if not is_guest_code_address(addr):
            raise SystemExit(f"Out-of-range guest seed in {path}: 0x{addr:08X}")
        seeds.add(addr)
    return seeds


def load_seed_addresses() -> set[int]:
    return read_seed_file(SEED_FILE) | read_seed_file(RUNTIME_SEEDS)


def load_canonical_manifest() -> str:
    if not os.path.exists(CANONICAL_MANIFEST):
        raise SystemExit(f"Canonical upstream manifest missing: {CANONICAL_MANIFEST}")
    text = read_text(CANONICAL_MANIFEST)
    canonical_targets = manifest_addresses(text)
    expected_targets = read_seed_file(SEED_FILE)
    if canonical_targets != expected_targets:
        missing = sorted(expected_targets - canonical_targets)
        extra = sorted(canonical_targets - expected_targets)
        raise SystemExit(
            "Canonical manifest / seed ledger drift: "
            f"missing={len(missing)} extra={len(extra)}"
        )
    return text


def manifest_addresses(text: str) -> set[int]:
    return {int(x, 16) for x in ENTRY_RE.findall(text)}


def append_targets(text: str, targets: set[int], prefix: str) -> tuple[str, list[int]]:
    existing = manifest_addresses(text)
    added = sorted(
        addr for addr in targets if is_guest_code_address(addr) and addr not in existing
    )
    if not added:
        return text, []
    text = text.rstrip() + "\n"
    for addr in added:
        text += (
            f"\n[entrypoint.functions.0x{addr:08X}]\n"
            f'name = "{prefix}_{addr:08X}"\n'
        )
    return text, added


def build_reset_manifest_text() -> tuple[str, list[int]]:
    text = load_canonical_manifest()
    runtime_targets = read_seed_file(RUNTIME_SEEDS)
    text, added = append_targets(text, runtime_targets, "runtime_target")
    return text, added


def reset_manifest() -> None:
    text, added = build_reset_manifest_text()
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(
        "Adaptive manifest reset: restored canonical upstream manifest "
        f"and added {len(added)} runtime-only target(s)."
    )


def scan_unresolved_targets() -> set[int]:
    targets: set[int] = set()
    files = sorted(glob.glob(os.path.join(GEN_DIR, "dantes_inferno_recomp.*.cpp")))
    for path in files:
        data = read_text(path)
        for match in CALL_RE.finditer(data):
            addr = int(match.group(1), 16)
            if is_guest_code_address(addr):
                targets.add(addr)
        for match in BRANCH_RE.finditer(data):
            addr = int(match.group(1), 16)
            if is_guest_code_address(addr):
                targets.add(addr)
    return targets


def close_manifest() -> int:
    if not os.path.exists(MANIFEST):
        print("Manifest is missing; run --reset first.", file=sys.stderr)
        return 2
    targets = scan_unresolved_targets()
    text = read_text(MANIFEST)
    text, added = append_targets(text, targets, "adaptive_target")
    if added:
        with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("Added direct unresolved targets:")
        for addr in added:
            print(f"  0x{addr:08X}")
    print(f"ADDED={len(added)}")
    return 0


def add_explicit_targets(raw_targets: list[str]) -> int:
    if not os.path.exists(MANIFEST):
        print("Manifest is missing; run --reset first.", file=sys.stderr)
        return 2
    targets: set[int] = set()
    for raw in raw_targets:
        try:
            addr = int(raw, 0) if raw.lower().startswith("0x") else int(raw, 16)
        except ValueError:
            print(f"Invalid target address: {raw}", file=sys.stderr)
            return 2
        if is_guest_code_address(addr):
            targets.add(addr)
    text = read_text(MANIFEST)
    text, added = append_targets(text, targets, "validation_target")
    if added:
        with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    for addr in added:
        print(f"Added validation target 0x{addr:08X}")
    print(f"ADDED={len(added)}")
    return 0


def learn_runtime_targets(log_path: str) -> int:
    if not os.path.exists(log_path):
        print(f"Runtime log not found: {log_path}", file=sys.stderr)
        return 2

    data = read_text(log_path)
    found: set[int] = set()
    for pattern in RUNTIME_TARGET_RES:
        for match in pattern.finditer(data):
            addr = int(match.group(1), 16)
            if is_guest_code_address(addr):
                found.add(addr)

    # Runtime learning is for genuinely new targets only. Do not duplicate
    # the 339 canonical upstream functions in the runtime ledger.
    existing = read_seed_file(SEED_FILE) | read_seed_file(RUNTIME_SEEDS)
    new = sorted(found - existing)

    if new:
        with open(RUNTIME_SEEDS, "a", encoding="utf-8", newline="\n") as f:
            if os.path.exists(RUNTIME_SEEDS) and os.path.getsize(RUNTIME_SEEDS):
                f.write("\n")
            for addr in new:
                f.write(f"0x{addr:08X}\n")
        print(f"Learned {len(new)} new runtime target(s):")
        for addr in new:
            print(f"  0x{addr:08X}")
    else:
        print("No new runtime targets found.")

    print(f"LEARNED={len(new)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--reset", action="store_true")
    action.add_argument("--close", action="store_true")
    action.add_argument("--add-targets", nargs="+", metavar="ADDR")
    action.add_argument("--learn-runtime-log", metavar="PATH")
    args = parser.parse_args()

    if args.reset:
        reset_manifest()
        return 0
    if args.close:
        return close_manifest()
    if args.add_targets:
        return add_explicit_targets(args.add_targets)
    if args.learn_runtime_log:
        return learn_runtime_targets(args.learn_runtime_log)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
