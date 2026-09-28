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


def reset_manifest() -> None:
    write_text(MANIFEST, MINIMAL_MANIFEST)
    print("Q01 manifest reset: foreign SKU hooks/function addresses removed.")
    print("ADDED=0")


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--close", action="store_true")
    args = parser.parse_args()

    if args.reset == args.close:
        parser.error("choose exactly one of --reset or --close")

    if args.reset:
        reset_manifest()
    else:
        close_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
