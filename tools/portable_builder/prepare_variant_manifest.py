#!/usr/bin/env python3
"""
Q01 SKU-adaptive manifest helper.

Hell's Gate upstream contains guest addresses manually discovered on another
retail XEX revision. Reusing those addresses on a different Media ID / XEX
revision can compile successfully while dispatching to the wrong guest code.

This helper creates a minimal manifest for the user's exact XEX/TU and then
iteratively adds only direct unresolved guest call/branch targets observed in
code generated from that image.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST = os.path.join(PROJECT_ROOT, "dantes_inferno_manifest.toml")
GEN_DIR = os.path.join(PROJECT_ROOT, "generated", "default")
SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "upstream_function_seeds.txt")
RUNTIME_SEEDS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "runtime_function_seeds.txt")

MINIMAL_MANIFEST = """# Q01 SKU-adaptive manifest.
# Generated locally from the user's preserved XEX/TU.

[project]
name = "dantes_inferno"
sdk_version = "0.10.0"
game_root = "game"

[entrypoint]
file_path = "game/default.xex"
out_directory_path = "generated/default"
includes = []
"""

UNRESOLVED_PATTERNS = (
    re.compile(r'REX_FATAL\("Unresolved call from 0x[0-9A-Fa-f]+ to 0x([0-9A-Fa-f]+)"\)'),
    re.compile(r'REX_FATAL\("Unresolved branch from 0x[0-9A-Fa-f]+ to 0x([0-9A-Fa-f]+)"\)'),
)
ENTRY_RE = re.compile(r'^\[entrypoint\.functions\.0x([0-9A-Fa-f]+)\]$', re.MULTILINE)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_seed_addresses() -> set[int]:
    seeds: set[int] = set()
    for path in (SEED_FILE, RUNTIME_SEEDS):
        if not os.path.isfile(path):
            continue
        for raw in read_text(path).splitlines():
            token = raw.split("#", 1)[0].strip()
            if not token:
                continue
            try:
                value = int(token, 0)
            except ValueError:
                print(f"WARNING: bad seed in {path}: {raw}", file=sys.stderr)
                continue
            if 0x82000000 <= value < 0x83000000:
                seeds.add(value)
    return seeds


def reset_manifest() -> None:
    manifest = MINIMAL_MANIFEST
    seeds = sorted(load_seed_addresses())
    if seeds:
        manifest += "\n# Proven upstream/runtime indirect function entrypoints.\n"
        for address in seeds:
            manifest += (
                f"\n[entrypoint.functions.0x{address:08X}]\n"
                f'name = "preservation_seed_{address:08X}"\n'
            )
    write_text(MANIFEST, manifest)
    print(f"Preservation manifest reset: retained {len(seeds)} proven function seeds.")
    print(f"ADDED={len(seeds)}")


def collect_unresolved() -> set[int]:
    targets: set[int] = set()
    for path in glob.glob(os.path.join(GEN_DIR, "dantes_inferno_recomp.*.cpp")):
        text = read_text(path)
        for pattern in UNRESOLVED_PATTERNS:
            for match in pattern.finditer(text):
                address = int(match.group(1), 16)
                # Xbox 360 title image range. Don't accidentally promote
                # kernel/import addresses to guest functions.
                if 0x82000000 <= address < 0x83000000:
                    targets.add(address)
    return targets


def add_targets(target_tokens: list[str]) -> int:
    manifest = read_text(MANIFEST)
    existing = {int(x, 16) for x in ENTRY_RE.findall(manifest)}
    new_targets: list[int] = []

    for token in target_tokens:
        token = token.strip()
        if token.lower().startswith("0x"):
            token = token[2:]
        try:
            address = int(token, 16)
        except ValueError:
            print(f"WARNING: ignoring invalid target token: {token}", file=sys.stderr)
            continue

        if not (0x82000000 <= address < 0x83000000):
            print(f"WARNING: ignoring target outside title image: 0x{address:08X}", file=sys.stderr)
            continue
        if address in existing:
            continue

        existing.add(address)
        new_targets.append(address)

    if new_targets:
        if not manifest.endswith("\n"):
            manifest += "\n"
        manifest += "\n# Auto-promoted validation targets for this exact XEX/TU.\n"
        for address in sorted(new_targets):
            manifest += (
                f"\n[entrypoint.functions.0x{address:08X}]\n"
                f'name = "q01_bootstrap_{address:08X}"\n'
            )
        write_text(MANIFEST, manifest)

    for address in sorted(new_targets):
        print(f"  + validation target 0x{address:08X}")
    print(f"ADDED={len(new_targets)}")
    return len(new_targets)


def close_manifest() -> None:
    if not os.path.isdir(GEN_DIR):
        print(f"ERROR: generated directory not found: {GEN_DIR}", file=sys.stderr)
        sys.exit(2)

    manifest = read_text(MANIFEST)
    existing = {int(x, 16) for x in ENTRY_RE.findall(manifest)}
    unresolved = collect_unresolved()
    new_targets = sorted(unresolved - existing)

    if new_targets:
        if not manifest.endswith("\n"):
            manifest += "\n"
        manifest += "\n# Auto-discovered targets for this exact XEX/TU.\n"
        for address in new_targets:
            manifest += (
                f"\n[entrypoint.functions.0x{address:08X}]\n"
                f'name = "q01_auto_{address:08X}"\n'
            )
        write_text(MANIFEST, manifest)

    print(f"Q01 unresolved closure: discovered={len(unresolved)} new={len(new_targets)}")
    for address in new_targets:
        print(f"  + 0x{address:08X}")
    print(f"ADDED={len(new_targets)}")


def learn_runtime_log(path: str) -> int:
    if not os.path.isfile(path):
        print(f"ERROR: runtime log not found: {path}", file=sys.stderr)
        return 2
    pattern = re.compile(
        r'Call to unresolved function at guest address 0x([0-9A-Fa-f]+)')
    found = {
        int(m.group(1), 16)
        for m in pattern.finditer(read_text(path))
        if 0x82000000 <= int(m.group(1), 16) < 0x83000000
    }
    known = load_seed_addresses()
    learned = sorted(found - known)
    if learned:
        with open(RUNTIME_SEEDS, "a", encoding="utf-8", newline="\n") as f:
            for address in learned:
                f.write(f"0x{address:08X}\n")
    print(f"Runtime learner: observed={len(found)} new={len(learned)}")
    for address in learned:
        print(f"  + learned 0x{address:08X}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--close", action="store_true")
    parser.add_argument("--add-targets", nargs="*", metavar="HEX")
    parser.add_argument("--learn-runtime-log", metavar="PATH")
    args = parser.parse_args()

    chosen = (int(args.reset) + int(args.close) +
              int(args.add_targets is not None) +
              int(args.learn_runtime_log is not None))
    if chosen != 1:
        parser.error("choose exactly one action")

    if args.reset:
        reset_manifest()
    elif args.close:
        close_manifest()
    elif args.learn_runtime_log:
        return learn_runtime_log(args.learn_runtime_log)
    else:
        add_targets(args.add_targets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
