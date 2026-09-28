#!/usr/bin/env python3
import importlib.util
import pathlib
import struct
import subprocess
import sys
import tempfile
import tomllib
import unittest

HERE = pathlib.Path(__file__).resolve().parent

def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    # dataclasses and other decorators resolve the defining module through
    # sys.modules while the module body is executing.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

runlog = load_module("runlog", "analyze_run_log.py")
manifest = load_module("manifest", "prepare_variant_manifest.py")
audit = load_module("audit", "preservation_audit.py")
langdet = load_module("langdet", "detect_disc_languages.py")

BASE = """XEX patch applied successfully: base version: 0.0.0.1, new version: 0.0.2.1
Q01 FIBER: cleared TU2 callback slot 0x82CE68E4
registered 36,677 functions
VdSwap: format=1, color_space=0, 1280x720, tiled=1
"""

def gate(report, gate_id):
    return next(g for g in report["gates"] if g["id"] == gate_id)

class RepositoryPolicyTests(unittest.TestCase):
    def test_manifest_is_valid_toml(self):
        repo_root = HERE.parents[1]
        with (repo_root / "dantes_inferno_manifest.toml").open("rb") as f:
            data = tomllib.load(f)
        self.assertEqual(data["project"]["name"], "dantes_inferno")
        self.assertEqual(data["entrypoint"]["file_path"], "game/default.xex")

    def test_no_commercial_game_binaries_are_tracked(self):
        repo_root = HERE.parents[1]
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
        forbidden_suffixes = (".xex", ".xexp", ".viv", ".iso", ".xiso", ".god", ".ciso", ".stfs")
        tracked = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip().lower().endswith(forbidden_suffixes)
        ]
        self.assertEqual(tracked, [], f"commercial game binaries tracked: {tracked}")

class RuntimeGateTests(unittest.TestCase):
    def test_unresolved_blocks_framebuffer_gate(self):
        data = BASE + """
[GPU GuestOutputCapture] frame=1 width=1280 height=720 stride=5120 bytes=3686400 nonzero=0 hash=0x1111
Call to invalid or unregistered function at guest address 0x8236E3C0
VFETCH-OOB: synthetic
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-0")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-2")["status"], "FAIL")
        self.assertEqual(gate(r, "GATE-3")["status"], "BLOCKED")
        self.assertEqual(r["metrics"]["unresolved_targets"]["0x8236E3C0"], 1)

    def test_early_zero_presenter_capture_is_inconclusive(self):
        data = BASE + """
[GPU GuestOutputCapture] frame=1 width=1280 height=720 stride=5120 bytes=3686400 nonzero=0 hash=0x2222
[GPU GuestOutputCapture] frame=32 width=1280 height=720 stride=5120 bytes=3686400 nonzero=0 hash=0x2222
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-2")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-3")["status"], "INCONCLUSIVE")

    def test_zero_presenter_output_through_horizon_fails_gate3(self):
        data = BASE + """
[GPU GuestOutputCapture] frame=1 width=1280 height=720 stride=5120 bytes=3686400 nonzero=0 hash=0x2222
[GPU GuestOutputCapture] frame=512 width=1280 height=720 stride=5120 bytes=3686400 nonzero=0 hash=0x2222
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-2")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-3")["status"], "FAIL")

    def test_nonzero_framebuffer_passes_gate3(self):
        data = BASE + """
[GPU GuestOutputCapture] frame=8 width=1280 height=720 stride=5120 bytes=3686400 nonzero=321 hash=0x3333
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-2")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-3")["status"], "PASS")

    def test_legacy_swapguest_is_not_authoritative_gate3_evidence(self):
        data = BASE + """
[GPU SwapGuest] ptr=0x1A000000 bytes=65536 nonzero=900 hash=0x7777
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-2")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-3")["status"], "INCONCLUSIVE")
        self.assertEqual(r["metrics"]["legacy_swapguest_nonzero_samples"], 1)
        self.assertTrue(any("LEGACY RENDER DIAGNOSTIC" in x for x in r["diagnosis"]))

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

    def test_subsystem_observations_do_not_promote_later_gates(self):
        data = BASE + """
SDL input driver initialized successfully
XMA: Registered MMIO handlers at 0x7FEA0000-0x7FEAFFFF
[GPU VP6 Draw] synthetic
XamContentCreateEx: sync result=0x0
XUserFindUsers(00000000, 00000000) - returning empty
user_language=5
DLC-MOD: synthetic
Initializing shader storage for title 454108CF...
[GPU GuestOutputCapture] frame=16 width=1280 height=720 stride=5120 bytes=3686400 nonzero=256 hash=0x4444
"""
        r = runlog.report(data)
        obs = r["metrics"]["observations"]
        for name in ("input_sdl", "audio_xma", "video_vp6", "save_content",
                     "language", "dlc", "shader"):
            self.assertGreater(obs[name], 0)
        self.assertEqual(gate(r, "GATE-3")["status"], "PASS")
        for gate_id in ("GATE-5", "GATE-8", "GATE-9", "GATE-10"):
            self.assertEqual(gate(r, gate_id)["status"], "UNVERIFIED")

    def test_faults_take_priority_after_gate2(self):
        data = BASE + """
[GPU GuestOutputCapture] frame=32 width=1280 height=720 stride=5120 bytes=3686400 nonzero=300 hash=0x5555
Unhandled guest access violation: read of guest 0x000001A4
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "GATE-2")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-3")["status"], "PASS")
        self.assertTrue(any("runtime fault evidence" in x for x in r["diagnosis"]))

    def test_historical_tu2_signature_is_classified(self):
        data = BASE + """
[GPU GuestOutputCapture] frame=1 width=1280 height=720 stride=5120 bytes=3686400 nonzero=0 hash=0x6666
Call to invalid or unregistered function at guest address 0x8236E3C0
"""
        r = runlog.report(data)
        ids = {item["id"] for item in r["historical_matches"]}
        self.assertIn("upstream-v0.6.3-v0.6.4-tu2-black-screen", ids)

    def test_save_language_filename_is_observed_without_promoting_gates(self):
        data = BASE + """
[GPU GuestOutputCapture] frame=8 width=1280 height=720 stride=5120 bytes=3686400 nonzero=100 hash=0x8888
XamContentCreate: root='savegame' saved=1 type=0x1 file='DI1-ES-0001' flags=0x4
XamContentCreateEx: sync result=0x0 disposition=2
XamContentClose: root='savegame' result=0x0
"""
        r = runlog.report(data)
        self.assertEqual(r["metrics"]["save_language_codes"], ["ES"])
        self.assertEqual(r["metrics"]["savedata_files"], ["DI1-ES-0001"])
        self.assertEqual(r["metrics"]["save_content_results"][0]["disposition"], 2)
        self.assertEqual(gate(r, "GATE-9")["status"], "UNVERIFIED")
        self.assertEqual(gate(r, "GATE-10")["status"], "UNVERIFIED")
        ids = {item["id"] for item in r["historical_matches"]}
        self.assertIn("upstream-save-language-filename-family", ids)

    def test_multiple_save_language_codes_are_reported(self):
        data = BASE + """
XamContentCreate: root='savegame' saved=1 type=0x1 file='DI1-EN-A' flags=0x4
XamContentCreate: root='savegame' saved=1 type=0x1 file='DI1-ES-A' flags=0x4
"""
        r = runlog.report(data)
        self.assertEqual(r["metrics"]["save_language_codes"], ["EN", "ES"])

    def test_clean_base_campaign_marker_passes_purity_subgate(self):
        data = BASE + """
DLC disabled for base-campaign preservation run.
[GPU GuestOutputCapture] frame=8 width=1280 height=720 stride=5120 bytes=3686400 nonzero=100 hash=0x9999
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "BASELINE-PURITY")["status"], "PASS")
        self.assertFalse(r["metrics"]["baseline_contamination"])

    def test_dlc_or_shader_seed_contaminates_base_run(self):
        data = BASE + """
DLC disabled for base-campaign preservation run.
Installing DLC package: example.dlm
Seeded 3 shader cache file(s) into C:/temp/shareable
[GPU GuestOutputCapture] frame=8 width=1280 height=720 stride=5120 bytes=3686400 nonzero=100 hash=0xAAAA
"""
        r = runlog.report(data)
        self.assertEqual(gate(r, "BASELINE-PURITY")["status"], "FAIL")
        self.assertTrue(r["metrics"]["baseline_contamination"])
        self.assertEqual(r["metrics"]["shader_cache_seeded_files"], 3)
        self.assertTrue(any("BASELINE CONTAMINATION" in x for x in r["diagnosis"]))

    def test_optional_bigfile_probes_are_not_filesystem_failures(self):
        data = BASE + """
[warning] [krnl] [NtCreateFile] FAILED: path='D:\\BIGFILE2.VIV' -> 0xc000000f
[warning] [krnl] [NtCreateFile] FAILED: path='D:\\BIGFILE12.VIV' -> 0xc000000f
[warning] [krnl] [NtCreateFile] FAILED: path='D:\\actually_required.bin' -> 0xc000000f
"""
        r = runlog.report(data)
        obs = r["metrics"]["observations"]
        self.assertEqual(obs["optional_viv_probe_misses"], 2)
        self.assertEqual(obs["filesystem_errors"], 1)
        self.assertTrue(any("optional BIGFILE2-12" in x for x in r["diagnosis"]))

    def test_sanitized_run005_regression_signature(self):
        data = """XEX patch applied successfully: base version: 0.0.0.1, new version: 0.0.2.1
Registered 36677 recompiled functions (0 duplicates, 0 rejected)
SDL input driver initialized successfully
XMA: Registered MMIO handlers at 0x7FEA0000-0x7FEAFFFF
Q01 FIBER: cleared TU2 callback slot 0x82CE68E4 (old=0x00000000)
VdSwap: format=6, color_space=0, 1280x720, tiled=1
[GPU VP6 Swap] frontbuffer_ptr=0xA001000 format=6 dim=1280x720
""" + (
            "Call to unresolved function at guest address 0x825D2C30 (returning)\n" * 22
        ) + (
            "Call to unresolved function at guest address 0x8236E3C0 (returning)\n" * 29
        ) + (
            "[NtCreateFile] FAILED: path='D:\\\\BIGFILE2.VIV' -> 0xc000000f\n" * 4
        ) + (
            "[NtCreateFile] FAILED: path='D:\\\\BIGFILE12.VIV' -> 0xc000000f\n" * 4
        ) + (
            "VFETCH-OOB: synthetic historical sample\n" * 49
        )
        r = runlog.report(data)
        self.assertEqual(r["metrics"]["registered_functions"], 36677)
        self.assertEqual(r["metrics"]["unresolved_dispatch_total"], 51)
        self.assertEqual(r["metrics"]["unresolved_targets"]["0x825D2C30"], 22)
        self.assertEqual(r["metrics"]["unresolved_targets"]["0x8236E3C0"], 29)
        self.assertTrue(r["metrics"]["fiber_callback_cleared"])
        self.assertEqual(r["metrics"]["vfetch_oob_count"], 49)
        self.assertEqual(r["metrics"]["observations"]["optional_viv_probe_misses"], 8)
        self.assertEqual(r["metrics"]["observations"]["filesystem_errors"], 0)
        self.assertEqual(gate(r, "GATE-0")["status"], "PASS")
        self.assertEqual(gate(r, "GATE-2")["status"], "FAIL")
        self.assertEqual(gate(r, "GATE-3")["status"], "BLOCKED")

    def test_xexp_signature_mismatch_is_classified(self):
        data = BASE + """
XEX patch signature hash doesn't match expected digest
"""
        r = runlog.report(data)
        ids = {item["id"] for item in r["historical_matches"]}
        self.assertIn("upstream-issue-51-xexp-signature-mismatch", ids)

class DiscLanguageTests(unittest.TestCase):
    def test_reads_authoritative_text_languages_from_synthetic_bigh(self):
        manifest_text = (
            "1\n"
            "454108CF-01\n"
            "meta\n"
            "default\n"
            "3\n"
            "2\n"
            "en\nEnglish\n1\nEN\n"
            "es\nSpanish\n5\nES\n"
            "it\nItalian\n6\nIT\n"
        ).encode("ascii")
        with tempfile.TemporaryDirectory() as tmp:
            game = pathlib.Path(tmp)
            viv = game / "bigfile0.viv"
            offset = 28
            header = (
                struct.pack(">I", langdet.BIG_MAGIC)
                + struct.pack("<I", offset + len(manifest_text))
                + struct.pack(">I", 1)
                + struct.pack("<I", offset)
                + struct.pack(">I", offset)
                + struct.pack(">I", len(manifest_text))
                + struct.pack("<I", 0)
            )
            viv.write_bytes(header + manifest_text)
            result = langdet.detect_game_dir(game)

        self.assertTrue(result["found"])
        manifest = result["manifest"]
        self.assertEqual(manifest["audio_count"], 2)
        self.assertEqual(
            [(x["id"], x["name"]) for x in manifest["text_languages"]],
            [(1, "English"), (5, "Spanish"), (6, "Italian")],
        )

    def test_invalid_archive_is_nonfatal_and_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = pathlib.Path(tmp)
            (game / "bigfile0.viv").write_bytes(b"not-a-big-archive")
            result = langdet.detect_game_dir(game)
        self.assertFalse(result["found"])


class ScannerPolicyTests(unittest.TestCase):
    def test_sdk_patch_uses_data_section_scanner_not_generic_wip_scanner(self):
        repo_root = HERE.parents[1]
        patch = (repo_root / "patches" / "sdk" / "rexglue-sdk-v0.10.0.patch").read_text(
            encoding="utf-8", errors="replace"
        )
        self.assertIn("void dataSectionFunctionPointerScan(CodegenContext& ctx)", patch)
        self.assertIn("+  dataSectionFunctionPointerScan(ctx);", patch)
        self.assertNotRegex(patch, r"(?m)^\+\s*functionPointerScan\(ctx\);\s*$")
        self.assertIn("[GPU GuestOutputCapture]", patch)
        self.assertNotIn("[GPU SwapGuest]", patch)
        self.assertIn("presenter->CaptureGuestOutput(capture)", patch)
        self.assertIn("XamContentCreate: root='{}' saved={}", patch)
        self.assertNotIn("NormalizeSaveFileName", patch)

class ManifestTests(unittest.TestCase):
    def test_reset_text_preserves_canonical_function_names(self):
        canonical = manifest.load_canonical_manifest()
        text, added = manifest.build_reset_manifest_text()
        self.assertEqual(added, [])
        self.assertEqual(text, canonical)
        self.assertIn("[entrypoint.functions.0x8236E3C0]", canonical)
        # This critical TU2 entry is intentionally unnamed upstream. Keeping
        # it unnamed makes ReXGlue emit the default sub_8236E3C0 symbol.
        self.assertIsNone(audit.manifest_function_names(canonical)[0x8236E3C0])

    def test_runtime_learning_does_not_duplicate_canonical_targets(self):
        old_runtime = manifest.RUNTIME_SEEDS
        try:
            with tempfile.TemporaryDirectory() as tmp:
                runtime_path = pathlib.Path(tmp) / "runtime_seeds.txt"
                log_path = pathlib.Path(tmp) / "run.log"
                manifest.RUNTIME_SEEDS = str(runtime_path)
                log_path.write_text(
                    "Call to invalid or unregistered function at guest address "
                    "0x8236E3C0\n"
                    "Call to invalid or unregistered function at guest address "
                    "0x82ABCDEF\n",
                    encoding="utf-8",
                )
                self.assertEqual(manifest.learn_runtime_targets(str(log_path)), 0)
                learned = runtime_path.read_text(encoding="utf-8")
                self.assertNotIn("0x8236E3C0", learned)
                self.assertIn("0x82ABCDEF", learned)
        finally:
            manifest.RUNTIME_SEEDS = old_runtime

    def test_base_manifest_preserves_upstream_midasm_hook(self):
        self.assertIn("0x824D6B90", manifest.load_canonical_manifest())
        self.assertIn("UltrawideAspectHook", manifest.load_canonical_manifest())

    def test_append_targets_is_cumulative_and_deduplicated(self):
        canonical = manifest.load_canonical_manifest()
        new_targets = {0x82ABC000, 0x82ABC100}
        self.assertTrue(new_targets.isdisjoint(manifest.manifest_addresses(canonical)))
        text, added = manifest.append_targets(
            canonical,
            new_targets,
            "test",
        )
        self.assertEqual(added, [0x82ABC000, 0x82ABC100])
        text2, added2 = manifest.append_targets(
            text,
            new_targets,
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
