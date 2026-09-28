#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent

def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

runlog = load_module("runlog", "analyze_run_log.py")
manifest = load_module("manifest", "prepare_variant_manifest.py")

BASE = """XEX patch applied successfully: base version: 0.0.0.1, new version: 0.0.2.1
Q01 FIBER: cleared TU2 callback slot 0x82CE68E4
registered 36,677 functions
VdSwap: format=1, color_space=0, 1280x720, tiled=1
"""

def gate(report, gate_id):
    return next(g for g in report["gates"] if g["id"] == gate_id)

class RuntimeGateTests(unittest.TestCase):
    def test_unresolved_blocks_framebuffer_gate(self):
        data = BASE + """
[GPU SwapGuest] ptr=0x1A000000 bytes=65536 nonzero=0 hash=0x1111
Call to invalid or unregistered function at guest address 0x8236E3C0
VFETCH-OOB: synthetic
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-0")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-2")["status"], "FAIL")
        self.assertEqual(gate(r, "GATE-3")["status"], "BLOCKED")
        self.assertEqual(r["metrics"]["unresolved_targets"]["0x8236E3C0"], 1)

    def test_zero_unresolved_zero_framebuffer_unlocks_renderer_diagnosis(self):
        data = BASE + """
[GPU SwapGuest] ptr=0x1A000000 bytes=65536 nonzero=0 hash=0x2222
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-2")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-3")["status"], "FAIL")

    def test_nonzero_framebuffer_passes_gate3(self):
        data = BASE + """
[GPU SwapGuest] ptr=0x1A000000 bytes=65536 nonzero=321 hash=0x3333
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-2")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-3")["status"], "PASS")

    def test_no_progress_is_not_false_pass(self):
        data = """XEX patch applied successfully: base version: 0.0.0.1, new version: 0.0.2.1
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-2")["status"], "INCONCLUSIVE")
        self.assertEqual(gate(r, "GATE-3")["status"], "BLOCKED")

    def test_old_unresolved_wording_is_still_understood(self):
        data = BASE + """
Unresolved call from 0x82100000 to 0x825D2C30
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-2")["status"], "FAIL")
        self.assertEqual(r["metrics"]["unresolved_targets"]["0x825D2C30"], 1)

class ManifestTests(unittest.TestCase):
    def test_base_manifest_preserves_upstream_midasm_hook(self):
        self.assertIn("0x824D6B90", manifest.BASE_MANIFEST)
        self.assertIn("UltrawideAspectHook", manifest.BASE_MANIFEST)

    def test_append_targets_is_cumulative_and_deduplicated(self):
        text, added = manifest.append_targets(
            manifest.BASE_MANIFEST,
            {0x8236E3C0, 0x825D2C30},
            "test",
        )
        self.assertEqual(added, [0x8236E3C0, 0x825D2C30])
        text2, added2 = manifest.append_targets(
            text,
            {0x8236E3C0, 0x825D2C30},
            "test",
        )
        self.assertEqual(added2, [])
        self.assertEqual(text2, text)

    def test_fail_fast_runtime_wording_is_learnable(self):
        line = "Call to invalid or unregistered function at guest address 0x8236E3C0"
        found = {
            int(m.group(1), 16)
            for pattern in manifest.RUNTIME_TARGET_RES
            for m in pattern.finditer(line)
        }
        self.assertEqual(found, {0x8236E3C0})

if __name__ == "__main__":
    unittest.main()
