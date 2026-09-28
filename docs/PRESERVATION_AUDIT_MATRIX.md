# PRESERVATION AUDIT MATRIX

This matrix tracks what is statically known, what has runtime evidence, and
what must remain deferred. "Present" is not equivalent to "validated in game."

| Area | Static/history finding | Automation / evidence | State |
|---|---|---|---|
| Manifest | 339 unique upstream function seeds + Ultrawide midasm hook | source CI compares ledger/manifest | PASS (source) |
| Function scanner | Direct/PDATA/vtable discovery is active; generic function-pointer scan is disabled upstream due false positives | preserved seeds + adaptive closure | AUDITED |
| Indirect calls / vtables | Upstream history proves static scanning can miss runtime targets | fail-fast dispatch + runtime seed learner | READY FOR GATE 2 |
| Tail calls | ReXGlue function graph models explicit tail calls and validates branch targets | generated direct traps must reach zero | AUDITED |
| Generated code | Fiber setjmp/longjmp detected by body signatures, known names only as guarded fallback | build fails if essential injections do not land | HARD-GATED |
| SDK invalid dispatch | Unknown indirect guest function is fatal, never silent-returned | source audit checks fail-fast invariant | PASS |
| TU2 / XEXP | normal module loader applies sibling XEXP before codegen BinaryView analysis | input hash gate + runtime TU version parser | GATE 0 |
| TU2 fibers | TU2 callback slot `0x82CE68E4`; full host/guest setjmp-longjmp bridge retained | build audit + runtime marker | READY |
| D3D12 presenter | D3D12 path, host vsync and guest-output diagnostics present | RUN log parser | DIAGNOSTIC READY |
| VdSwap / SwapGuest | VdSwap metadata + 64 KiB guest-frontbuffer nonzero/hash sampling | automatic GATE 3 parser | BLOCKED BY GATE 2 |
| VFETCH | OOB diagnostic exists; upstream history used it as a diagnostic, not universal root cause | warning count in RUN report | SECONDARY |
| Shader pipeline | Current SDK patch contains translator/cache/render fixes inherited from upstream; RUN00 intentionally does not seed foreign shader caches | inspect only after non-zero framebuffer | DEFERRED |
| Physics / VMX math | `vmsum3fp128` and related SDK corrections are present | static patch invariant available | PRESENT / NOT GAME-VALIDATED |
| Texture path | `gpu_3d_to_2d_texture` safety default and integer texture scaling changes present | static patch | PRESENT / NOT GAME-VALIDATED |
| Audio | Upstream history records an audio-init/XMA worker fix in the patch lineage | no GATE 8 evidence yet | DEFERRED |
| FMV/video | Upstream history records VMX/FMV corruption work; exact runtime behavior not yet demonstrated here | GATE 8 | DEFERRED |
| Input | SDL input baseline and project keybind work exist | GATE 5 | DEFERRED |
| Filesystem/VIV | Known VIV files validated as local preserved inputs; no game files committed | GATE 0 + later gameplay traversal | PARTIAL |
| Save/load | XUserFindUsers success/empty handler is present | GATE 9 | PRESENT / UNVERIFIED |
| Language | upstream fixed-address generated fallback is intentionally disabled in preservation-autofix | must become signature/structure based | GATE 10 DEFERRED |
| Save across languages | historical NormalizeSaveFileName patch existed but is not in current upstream SDK patch either | investigate before GATE 9/10; do not resurrect blindly | HISTORICAL / DEFERRED |
| DLC | DLC tracing/support exists in patch lineage | campaign first, then GATE 12 | DEFERRED |
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
- A zero guest framebuffer after a successful host present is not sufficient
  evidence of a renderer bug while unresolved guest logic remains.

## Next unlock condition

The next runtime investigation is intentionally narrow:

1. GATE 1 must pass the build-time exhaustive audit.
2. A real RUN must reach renderer progress.
3. GATE 2 must report exactly zero unresolved guest dispatches.
4. Only then may a zero framebuffer promote renderer/shader/VFETCH work to the
   primary diagnosis.

This ordering prevents renderer tweaks from masking missing guest execution.
