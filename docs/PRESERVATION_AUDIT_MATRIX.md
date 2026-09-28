# PRESERVATION AUDIT MATRIX

This matrix tracks what is statically known, what has runtime evidence, and
what must remain deferred. "Present" is not equivalent to "validated in game."

| Area | Static/history finding | Automation / evidence | State |
|---|---|---|---|
| Manifest | Canonical upstream snapshot preserves all 339 entrypoints, their original names/unnamed TU2 semantics, and corrected `0x824D6B90/f0` hook | exact Git-blob pin + seed fingerprint + root-name comparison | PASS (source) |
| Function scanner | Direct/PDATA/RTTI-vtable discovery is active; generic WIP pointer scan stays disabled; conservative data-section pointer scan is enabled | CI policy check + per-pass scanner evidence retained | AUDITED / HARD-GATED IN BUILD |
| Indirect calls / vtables | Upstream history proves static scanning can miss runtime targets; runtime learner now excludes all 339 canonical targets and records only genuinely new addresses | fail-fast dispatch + deduplicated runtime seed learner | READY FOR GATE 2 |
| Tail calls | ReXGlue function graph models explicit tail calls and validates branch targets | generated direct traps must reach zero | AUDITED |
| Generated code | Fiber setjmp/longjmp detected by body signatures, known names only as guarded fallback | build fails if essential injections do not land | HARD-GATED |
| SDK invalid dispatch | Pinned ReXGlue v0.10.0 is natively fail-fast; preservation patch deliberately does not override dispatcher and CI forbids upstream-style `log + return` regression | source audit + pristine SDK patch-apply check | PASS |
| TU2 / XEXP | normal module loader applies sibling XEXP before codegen BinaryView analysis | input hash gate + runtime TU version parser | GATE 0 |
| TU2 fibers | TU2 callback slot `0x82CE68E4`; full host/guest setjmp-longjmp bridge retained | build audit + runtime marker | READY |
| D3D12 presenter | D3D12 path, host vsync and guest-output diagnostics present | RUN log parser | DIAGNOSTIC READY |
| GATE 3 presenter output | Old `SwapGuest` raw guest-memory samples are non-authoritative in D3D12; actual presentation comes from `TextureFetch(0) -> RequestSwapTexture()` | sparse `Presenter::CaptureGuestOutput()` GPU readback through frame 512 | BLOCKED BY GATE 2 / INSTRUMENTED |
| VFETCH | OOB diagnostic exists; upstream history used it as a diagnostic, not universal root cause | warning count in RUN report | SECONDARY |
| Shader pipeline | Current SDK patch contains translator/cache/render fixes inherited from upstream; RUN00 intentionally does not seed foreign shader caches | inspect only after non-zero framebuffer | DEFERRED |
| Physics / VMX math | `vmsum3fp128` and related SDK corrections are present | static patch invariant available | PRESENT / NOT GAME-VALIDATED |
| Texture path | `gpu_3d_to_2d_texture` safety default and integer texture scaling changes present | static patch | PRESENT / NOT GAME-VALIDATED |
| Audio | Both known XMA synchronization/inline-decode fixes predate and are ancestors of pinned ReXGlue v0.10.0 | runtime subsystem observations; no GATE 8 evidence yet | PRESENT IN BASE SDK / UNVERIFIED |
| FMV/video | Upstream history records VMX/FMV corruption work; exact runtime behavior not yet demonstrated here | GATE 8 | DEFERRED |
| Input | SDL backend; complete M&K defaults are applied only when the user has not overridden them | source binding audit + runtime `input_sdl` observation + GATE 5 | PRESENT / UNVERIFIED |
| Filesystem/VIV | Working upstream layout documents `default.xex + bigfile0.viv + bigfile1.viv`; GATE 0 validates those local preserved inputs; no commercial files are tracked | input checks + filesystem observations + Git policy test | PARTIAL / RUNTIME UNVERIFIED |
| Save/load | XUserFindUsers safe-empty handler is present; XamContent lifecycle is instrumented without filename mutation | RUN report records savedata names/results/dispositions; GATE 9 | PRESENT / UNVERIFIED |
| Language | authoritative BIGH/VIV text-language parser selects only a language actually present on disc; locale country ID follows upstream mapping. Fixed-address generated fallback remains disabled | `disc-languages.json`, GATE-0-LANG, provenance; Spanish only if ID 5 present | BASELINE DETECTION PASS / GATE 10 DEFERRED |
| Save across languages | ReXGlue uses `file_name` as the physical package path, so `DI1-EN-*` / `DI1-ES-*` differ. Upstream explicitly reverted destructive NormalizeSaveFileName | observe language-coded filenames first; design non-destructive compatibility only after GATE 9/10 evidence | KNOWN COUPLING / DEFERRED |
| DLC | DLC support exists but is opt-in; base RUN forces `enable_dlc=false` and uses isolated `userdata_base` state | source audit + runtime BASELINE-PURITY subgate | ISOLATED UNTIL GATE 12 |
| Protected install paths | upstream issue #69 points to `InitLogging` filesystem exceptions under Program Files; preservation uses user-data logs, non-throwing directory creation, sink-error reporting, and LocalAppData launcher fallback | pristine SDK patch-apply CI + PowerShell parse | FIXED STATICALLY / RUNTIME UNVERIFIED |
| Reproducibility | RUN package records source commit, SDK commit/tag, patch hash, canonical/generated manifests, ledgers, generated register, static audit and EXE/DLL hashes | `BUILD_PROVENANCE.json` required by source audit | PASS (build policy) |
| Modernization | render scaling, cache, ultrawide and other enhancements exist upstream in various forms | only after campaign gates | GATE 13 DEFERRED |

## Historical upstream lessons retained

- `rexglue init --force` has previously wiped manifest entries and hooks.
  Preservation-autofix therefore rebuilds from an explicit ledger rather than
  trusting regeneration to preserve knowledge.
- Upstream has documented TU2 functions reachable only through indirect
  dispatch; this is why the seed ledger is authoritative evidence, not cruft.
- Function-pointer scanning has produced large false-positive sets upstream and
  is not a safe replacement for proven runtime targets.
- Generated file indices are unstable across codegen. Fiber patching therefore
  searches function bodies/signatures rather than hardcoding
  `dantes_inferno_recomp.N.cpp`.
- Raw `SwapGuest` memory is not authoritative for D3D12 presentation at all.
  Renderer conclusions require `CaptureGuestOutput()` readback, and GATE 3
  remains blocked while unresolved guest logic exists.

## Next unlock condition

The next runtime investigation is intentionally narrow:

1. GATE 1 must pass the build-time exhaustive audit.
2. A real RUN must reach renderer progress.
3. GATE 2 must report exactly zero unresolved guest dispatches.
4. Only then may authoritative presenter readback remaining zero through frame
   512 promote renderer/shader/VFETCH work to the primary diagnosis.

This ordering prevents renderer tweaks from masking missing guest execution.


## Upstream parity snapshot

At the current audit point, the following critical project files are byte-for-byte
identical to current `florinp93/hells-gate-recomp`:

- `dantes_inferno_manifest.toml`
- `CMakeLists.txt`
- `CMakePresets.json`
- `setup.ps1`
- `src/dantes_inferno_hooks.h`

Intentional divergences:

- `src/dantes_inferno_app.h`: preservation requires the validated TU2 image and
  therefore clears the known TU2 fiber callback slot directly, with an explicit
  runtime marker.
- `patches/generated/apply_generated_patches.py`: preservation turns missing
  fiber fixes/direct unresolved traps into hard build failures and deliberately
  withholds the fixed-address language fallback until it can be tied safely to
  the validated image/signature.
- SDK patch: the vast majority matches current upstream. Preservation adds
  sparse authoritative presenter-readback diagnostics and protected-path logging robustness, drops
  the dirty libmspack gitlink artifact, and refuses the current upstream
  silent-return `InvalidFunctionTrap` behavior.

## Reproducibility evidence

A packaged RUN is not identified only by a folder name. `BUILD_PROVENANCE.json`
records the exact source/SDK state and output hashes, while
`preservation-evidence/codegen-pass-XX.log` retains scanner/codegen evidence.
This allows two RUN packages to be compared without relying on memory or manual
notes.
