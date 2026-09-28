#!/usr/bin/env python3
"""Verify preservation-critical invariants in an actually patched ReXGlue SDK."""

from __future__ import annotations

import argparse
from pathlib import Path


def require(text: str, needle: str, label: str, failures: list[str]) -> None:
    if needle not in text:
        failures.append(f"{label}: missing {needle!r}")


def forbid(text: str, needle: str, label: str, failures: list[str]) -> None:
    if needle in text:
        failures.append(f"{label}: forbidden {needle!r} is present")


def read(root: Path, relative: str) -> str:
    path = root / relative
    if not path.exists():
        raise SystemExit(f"missing SDK file: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sdk_root")
    args = parser.parse_args()
    root = Path(args.sdk_root).resolve()
    failures: list[str] = []

    xma = read(root, "src/audio/xma_decoder.cpp")
    require(
        xma,
        "Decode inline. waiting on the worker sweep stalls the realtime",
        "XMA inline decode",
        failures,
    )
    require(xma, "context.SignalWorkDone();", "XMA completion", failures)
    require(xma, "context.Block(false);", "XMA disable synchronization", failures)

    vector = read(root, "src/codegen/builders/vector.cpp")
    require(vector, "bool build_vmaddcfp128", "VMX multiply-add", failures)
    require(
        vector,
        "dp_ps 0xEF: sums host elements 1-3",
        "VMX vmsum3fp128 mask",
        failures,
    )
    require(
        vector,
        "Operands swapped for the byte-reversed layout.",
        "VMX pack operand order",
        failures,
    )

    xlive = read(root, "src/kernel/xam/apps/xlivebase_app.cpp")
    require(xlive, "case 0x0005000E:", "XUserFindUsers dispatch", failures)
    require(
        xlive,
        "XUserFindUsers({:08X}, {:08X}) - returning empty",
        "XUserFindUsers safe empty result",
        failures,
    )

    content = read(root, "src/kernel/xam/xam_content.cpp")
    require(
        content,
        "XamContentCreate: root='{}' saved={} type={:#X} file='{}' flags={:#X}",
        "savedata lifecycle diagnostics",
        failures,
    )
    forbid(
        content,
        "NormalizeSaveFileName",
        "non-mutating savedata policy",
        failures,
    )

    d3d12 = read(root, "src/graphics/d3d12/command_processor.cpp")
    require(
        d3d12,
        "[GPU GuestOutputCapture]",
        "authoritative presenter capture",
        failures,
    )
    require(
        d3d12,
        "presenter->CaptureGuestOutput(capture)",
        "presenter readback",
        failures,
    )
    forbid(d3d12, "[GPU SwapGuest]", "legacy raw-memory gate", failures)

    logging = read(root, "src/core/logging.cpp")
    require(
        logging,
        "std::filesystem::create_directories(logs_dir, create_ec)",
        "non-throwing log directory creation",
        failures,
    )
    require(
        logging,
        "catch (const spdlog::spdlog_ex& e)",
        "non-fatal log sink creation",
        failures,
    )

    rex_app = read(root, "src/ui/rex_app.cpp")
    require(
        rex_app,
        "user_data_root_.empty() ? (exe_dir / \"logs\") : (user_data_root_ / \"logs\")",
        "writable log root",
        failures,
    )

    dispatcher = read(root, "src/system/function_dispatcher.cpp")
    require(
        dispatcher,
        'REX_FATAL("Call to invalid or unregistered function at guest address 0x{:08X}"',
        "fail-fast invalid guest dispatch",
        failures,
    )
    forbid(
        dispatcher,
        "Call to unresolved function at guest address 0x{:08X} (returning)",
        "silent invalid guest dispatch",
        failures,
    )

    if failures:
        print("Patched SDK preservation verification FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("Patched SDK preservation verification PASS")
    print("  XMA synchronization/inline-decode invariants present")
    print("  VMX/FMV vector fixes present")
    print("  XUserFindUsers safe-empty handler present")
    print("  Savedata diagnostics are non-mutating")
    print("  GATE 3 uses actual presenter readback")
    print("  Protected-path logging is non-fatal")
    print("  Invalid guest dispatch remains fail-fast")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
