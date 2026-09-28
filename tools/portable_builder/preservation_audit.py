#!/usr/bin/env python3
"""Static preservation gates for the Dante's Inferno native recomp."""

from __future__ import annotations
import argparse, hashlib, json, re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

TITLE_ID = "454108CF"
MEDIA_ID = "49028C6A"
EXPECTED_UPSTREAM_SEEDS = 339
EXPECTED_SEED_FNV1A64 = 0x2F1669F5BE191238
CRITICAL_INDIRECT_TARGETS = {0x8236E3C0, 0x825D2C30}
EXPECTED_INPUTS = {
    "default.xex": {"size": 10760192, "sha256": "abfef19fa03a247ab17d5c011e34ca70a0338f13c15b7fd8932c7ff7d9e2c2e9"},
    "default.xexp": {"size": 2205696, "sha256": "0842733820a27e0c902e6a652b3cd71d2c4a05f36db5121c1d342416a6b7ab09"},
    "bigfile0.viv": {"size": 3176365408, "sha256": None},
    "bigfile1.viv": {"size": 2692050613, "sha256": None},
}
MANIFEST_ENTRY_RE = re.compile(r"^\[entrypoint\.functions\.0x([0-9A-Fa-f]+)\]$", re.MULTILINE)
REGISTER_RE = re.compile(r"registrar->SetFunction\(0x([0-9A-Fa-f]+),\s*(\w+)\)")
UPSTREAM_HOOK_RE = re.compile(
    r"\[\[midasm_hook\]\]\s*address\s*=\s*0x824D6B90\s*"
    r'name\s*=\s*"UltrawideAspectHook"\s*registers\s*=\s*\[\s*"f0"\s*\]',
    re.MULTILINE,
)

@dataclass
class Check:
    id: str
    status: str
    summary: str
    details: list[str]

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def parse_seed_file(path: Path) -> tuple[list[int], list[str]]:
    values, errors = [], []
    if not path.exists():
        return values, [f"missing {path}"]
    for lineno, raw in enumerate(read_text(path).splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            addr = int(line, 0)
        except ValueError:
            errors.append(f"{path.name}:{lineno}: invalid address {line!r}")
            continue
        if not 0x82000000 <= addr < 0x83000000:
            errors.append(f"{path.name}:{lineno}: out-of-range 0x{addr:08X}")
            continue
        values.append(addr)
    return values, errors

def manifest_addresses(text: str) -> list[int]:
    return [int(m.group(1), 16) for m in MANIFEST_ENTRY_RE.finditer(text)]

def seed_fingerprint(values: Iterable[int]) -> int:
    canonical = "".join(f"0x{value:08X}\\n" for value in sorted(set(values)))
    h = 0xCBF29CE484222325
    for byte in canonical.encode("ascii"):
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h

def add_check(checks: list[Check], cid: str, ok: bool, summary: str, details: Iterable[str] = ()) -> None:
    checks.append(Check(cid, "PASS" if ok else "FAIL", summary, list(details)))

def source_checks(root: Path) -> list[Check]:
    checks = []
    tools_dir = root / "tools" / "portable_builder"
    seeds, seed_errors = parse_seed_file(tools_dir / "upstream_function_seeds.txt")
    seed_set = set(seeds)
    duplicates = len(seeds) - len(seed_set)
    missing_critical = sorted(CRITICAL_INDIRECT_TARGETS - seed_set)
    fingerprint = seed_fingerprint(seed_set)
    fingerprint_ok = fingerprint == EXPECTED_SEED_FNV1A64
    add_check(checks, "SRC-SEEDS",
        not seed_errors and len(seed_set) == EXPECTED_UPSTREAM_SEEDS and duplicates == 0
        and not missing_critical and fingerprint_ok,
        f"upstream seed ledger: {len(seed_set)} unique targets; fingerprint=0x{fingerprint:016X}",
        [*seed_errors,
         *([f"expected {EXPECTED_UPSTREAM_SEEDS}, got {len(seed_set)}"] if len(seed_set) != EXPECTED_UPSTREAM_SEEDS else []),
         *([f"duplicates={duplicates}"] if duplicates else []),
         *([f"missing critical: {', '.join(f'0x{x:08X}' for x in missing_critical)}"] if missing_critical else []),
         *([f"seed-set fingerprint mismatch: expected 0x{EXPECTED_SEED_FNV1A64:016X}, got 0x{fingerprint:016X}"] if not fingerprint_ok else [])])

    manifest_path = root / "dantes_inferno_manifest.toml"
    if manifest_path.exists():
        manifest = read_text(manifest_path)
        entries, entry_set = manifest_addresses(manifest), set(manifest_addresses(manifest))
        missing_seeds = sorted(seed_set - entry_set)
        hook_ok = bool(UPSTREAM_HOOK_RE.search(manifest))
        add_check(checks, "SRC-MANIFEST",
            len(entries) == len(entry_set) and not missing_seeds and hook_ok,
            f"manifest: {len(entry_set)} unique function entries; upstream hook {'present' if hook_ok else 'missing'}",
            [*([f"duplicate function entries={len(entries)-len(entry_set)}"] if len(entries) != len(entry_set) else []),
             *([f"missing {len(missing_seeds)} seed(s): " + ", ".join(f"0x{x:08X}" for x in missing_seeds[:20])] if missing_seeds else []),
             *(["missing preserved midasm hook 0x824D6B90 UltrawideAspectHook(f0)"] if not hook_ok else [])])
    else:
        add_check(checks, "SRC-MANIFEST", False, "manifest missing", [str(manifest_path)])

    helper_path = tools_dir / "prepare_variant_manifest.py"
    helper = read_text(helper_path) if helper_path.exists() else ""
    helper_ok = "0x824D6B90" in helper and "UltrawideAspectHook" in helper and "invalid or unregistered" in helper and "--learn-runtime-log" in helper
    add_check(checks, "SRC-ADAPTIVE-MANIFEST", helper_ok,
        "adaptive manifest preserves upstream metadata and fail-fast runtime learning",
        [] if helper_ok else ["helper must preserve upstream midasm metadata and parse current fail-fast logs"])

    sdk_patch_path = root / "patches" / "sdk" / "rexglue-sdk-v0.10.0.patch"
    patch = read_text(sdk_patch_path) if sdk_patch_path.exists() else ""
    dirty_gitlink = bool(re.search(r"^\+Subproject commit .*?-dirty\s*$", patch, re.M))
    trap_pos = patch.find("static void InvalidFunctionTrap")
    trap_chunk = patch[trap_pos:trap_pos + 500] if trap_pos >= 0 else ""
    fail_fast = "REX_FATAL" in trap_chunk and "last_indirect_target" in trap_chunk
    add_check(checks, "SRC-SDK-PATCH", bool(patch) and not dirty_gitlink and fail_fast,
        "SDK patch keeps invalid indirect dispatch fail-fast and has no dirty gitlinks",
        [*(["patch contains non-reproducible 'Subproject commit ...-dirty'"] if dirty_gitlink else []),
         *(["InvalidFunctionTrap fail-fast invariant not found"] if not fail_fast else [])])

    app_path, hooks_path = root / "src" / "dantes_inferno_app.h", root / "src" / "dantes_inferno_hooks.h"
    app = read_text(app_path) if app_path.exists() else ""
    hooks = read_text(hooks_path) if hooks_path.exists() else ""
    fiber_ok = "0x82CE68E4" in app and "FiberSetjmp" in hooks and "FiberLongjmp" in hooks and "FiberRestoreContext" in hooks
    add_check(checks, "SRC-TU2-FIBERS", fiber_ok, "TU2 fiber callback + setjmp/longjmp support preserved",
              [] if fiber_ok else ["missing TU2 callback slot or fiber helper invariant"])

    builder_path = tools_dir / "Build-DantePortable.ps1"
    builder = read_text(builder_path) if builder_path.exists() else ""
    builder_ok = "preservation-autofix" in builder and "preservation_audit.py" in builder and "analyze_run_log.py" in builder and "RUN 00 BUILD PASS" not in builder
    add_check(checks, "SRC-BUILDER-POLICY", builder_ok,
        "builder distinguishes build/static readiness from runtime functionality",
        [] if builder_ok else ["builder must invoke gate tools and never label a merely compiled EXE as runtime PASS"])
    return checks

def input_checks(root: Path, required: bool) -> list[Check]:
    game, details, missing, bad = root / "game", [], [], []
    for name, spec in EXPECTED_INPUTS.items():
        path = game / name
        if not path.exists():
            missing.append(name); continue
        if path.stat().st_size != spec["size"]:
            bad.append(f"{name}: size mismatch"); continue
        if spec["sha256"] and sha256_file(path).lower() != spec["sha256"].lower():
            bad.append(f"{name}: SHA-256 mismatch")
    if missing: details.append("missing: " + ", ".join(missing))
    details.extend(bad)
    if missing and not required and not bad:
        return [Check("GATE-0", "SKIP", f"retail inputs unavailable in source-only audit (Title {TITLE_ID}, Media {MEDIA_ID})", details)]
    ok = not missing and not bad
    return [Check("GATE-0", "PASS" if ok else "FAIL", "known retail inputs/hash/TU2 validated" if ok else "retail input validation failed", details)]

def generated_checks(root: Path, required: bool) -> list[Check]:
    gen = root / "generated" / "default"
    register_path = gen / "dantes_inferno_register.cpp"
    files = sorted(gen.glob("dantes_inferno_recomp.*.cpp")) if gen.exists() else []
    if not register_path.exists() or not files:
        status = "FAIL" if required else "SKIP"
        return [Check("GATE-1", status, "fresh generated code unavailable" if status == "SKIP" else "fresh generated code required but missing", [str(gen)])]
    seeds, seed_errors = parse_seed_file(root / "tools" / "portable_builder" / "upstream_function_seeds.txt")
    seed_set = set(seeds)
    registered = {int(m.group(1), 16) for m in REGISTER_RE.finditer(read_text(register_path))}
    missing = sorted(seed_set - registered)
    all_generated = "\n".join(read_text(p) for p in files)
    unresolved_direct = len(re.findall(r'REX_FATAL\("Unresolved (?:call|branch)', all_generated))
    details = list(seed_errors)
    if missing: details.append(f"{len(missing)} preserved seed(s) absent from generated registration: " + ", ".join(f"0x{x:08X}" for x in missing[:30]))
    if unresolved_direct: details.append(f"remaining generated direct unresolved traps={unresolved_direct}")
    if "FiberSetjmp" not in all_generated: details.append("FiberSetjmp injection not present")
    if "FiberLongjmp" not in all_generated: details.append("FiberLongjmp injection not present")
    return [Check("GATE-1", "PASS" if not details else "FAIL",
        f"codegen audit: {len(registered)} registered functions; {len(seed_set)-len(missing)}/{len(seed_set)} preserved seeds registered", details)]

def gate2_readiness(checks: list[Check]) -> Check:
    gate1 = next((c for c in checks if c.id == "GATE-1"), None)
    if gate1 and gate1.status == "PASS":
        return Check("GATE-2", "UNVERIFIED", "runtime zero-unresolved gate is ready for log evidence", ["static codegen cannot prove all indirect runtime targets are exercised"])
    return Check("GATE-2", "BLOCKED", "runtime unresolved-function gate blocked by GATE-1", [])

def write_outputs(json_path: str | None, md_path: str | None, mode: str, checks: list[Check]) -> None:
    payload = {"schema": 1, "audit": "dantes-inferno-preservation-static", "mode": mode,
               "title_id": TITLE_ID, "media_id": MEDIA_ID, "checks": [asdict(c) for c in checks]}
    if json_path:
        p=Path(json_path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(payload, indent=2)+"\n", encoding="utf-8")
    if md_path:
        p=Path(md_path); p.parent.mkdir(parents=True, exist_ok=True)
        lines=["# Dante's Inferno Preservation Static Audit","",f"- Mode: `{mode}`",f"- Title ID: `{TITLE_ID}`",f"- Media ID: `{MEDIA_ID}`","",
               "| Check | Status | Result |","|---|---|---|"]
        lines += [f"| `{c.id}` | **{c.status}** | {c.summary} |" for c in checks]
        lines += ["","A successful compilation is not a functional PASS. Runtime gates begin only after GATE-1.",""]
        p.write_text("\n".join(lines), encoding="utf-8")

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--root"); ap.add_argument("--mode", choices=("source","build"), default="source")
    ap.add_argument("--json", dest="json_path"); ap.add_argument("--markdown", dest="md_path"); args=ap.parse_args()
    root=Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[2]
    checks=source_checks(root)+input_checks(root,args.mode=="build")+generated_checks(root,args.mode=="build"); checks.append(gate2_readiness(checks))
    for c in checks:
        print(f"[{c.status:10}] {c.id:22} {c.summary}")
        for d in c.details: print(f"             - {d}")
    write_outputs(args.json_path,args.md_path,args.mode,checks)
    return 1 if any(c.status=="FAIL" for c in checks) else 0
if __name__ == "__main__":
    raise SystemExit(main())
