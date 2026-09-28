# DANTE'S INFERNO — PRESERVATION AUTOFIX

This branch is the cumulative preservation/debug branch built on top of
florinp93/hells-gate-recomp and ReXGlue v0.10.0.

## Why it exists

RUN00(5) proved that TU2 loads and the D3D12 renderer reaches the guest swap
path while runtime dispatch repeatedly reached unregistered guest functions.
Its old `SwapGuest` diagnostic also sampled zeroed raw guest memory, but later
renderer audit proved that pointer is **not** the authoritative D3D12
presentation source; GATE 3 no longer uses it.

The previous Q01 "minimal manifest" strategy was wrong for this title: static
closure cannot rediscover every vtable / computed / indirect target. Upstream
history independently documents the same class of failure.

## Preservation policy

1. Never mask an unresolved guest function by returning from it. Fail fast.
2. Preserve all upstream entrypoints already proven necessary.
3. Preserve non-function upstream manifest knowledge too (for example
   `UltrawideAspectHook` at `0x824D6B90`).
4. Layer exact-SKU static discovery on top of that preserved knowledge.
5. Learn additional runtime targets from logs.
6. Delete/regenerate codegen deterministically and patch generated code before
   compilation.
7. Refuse packaging when source/build preservation gates fail.
8. Keep user game data out of Git.
9. Compilation is never called a runtime PASS.

The current upstream seed ledger contains exactly **339 unique function
entrypoints**. `preservation_audit.py` checks all of them, not just the two
addresses seen in RUN00(5).

## Proven preserved retail inputs

- Title ID: `454108CF`
- Media ID: `49028C6A`
- base `default.xex`: `0.0.0.1`
- TU2 `default.xexp`: `0.0.2.1`
- `default.xex` SHA-256:
  `abfef19fa03a247ab17d5c011e34ca70a0338f13c15b7fd8932c7ff7d9e2c2e9`
- `default.xexp` SHA-256:
  `0842733820a27e0c902e6a652b3cd71d2c4a05f36db5121c1d342416a6b7ab09`

The original VIV archives are validated by expected size by the portable
builder and are never committed.

## Historical regression match

The canonical entrypoint ledger is not an arbitrary collection. A direct
comparison against upstream tag `v0.6.4-beta` shows that the release manifest
contains exactly **339 function entrypoints**, and
`upstream_function_seeds.txt` contains exactly the same 339-address set.

This matters because upstream's release history records the same failure chain:

- `v0.6.3-beta` explicitly restored TU2 entrypoints including
  `0x8236E3C0` and `0x825D2C30`.
- `v0.6.4-beta` added the remaining TU2/codegen coverage, patched all known
  setjmp/longjmp sites and reported zero remaining generated unresolved traps.
- Upstream issue #55 reported a black screen after selecting difficulty on
  v0.6.0; the reporter later confirmed a clean v0.6.4-beta install worked.

The preservation auditor fingerprints the canonical v0.6.4 function ledger
(`0x2F1669F5BE191238` using the auditor's FNV-1a canonicalization) so a future
regeneration cannot silently substitute a different 339-address set.

This does **not** prove our next runtime will pass: it proves that the known
function-coverage baseline that fixed the historical TU2 regression has been
restored exactly. Runtime GATE 2 still requires real execution evidence.

## RUN00(5) finding

Two runtime targets dominated the failure:

- `0x825D2C30` — 22 calls
- `0x8236E3C0` — 29 calls

Both were already present in the upstream Hell's Gate manifest. The old
minimal-manifest reset discarded them. That explains how an executable could
compile yet run with missing guest logic.

The same log showed `VdSwap` at 1280x720 while every old `SwapGuest`
raw-memory sample was zero. D3D12 `IssueSwap` actually presents the resource
resolved through `TextureFetch(0) -> RequestSwapTexture()`, so those samples
are retained only as historical evidence. The preservation branch now uses
`Presenter::CaptureGuestOutput()` to read back the actual image submitted by
the presenter. `VFETCH-OOB` remains diagnostic/secondary until GATE 2 is
proven.

## XEX / XEXP during codegen

ReXGlue codegen does not analyze an isolated bare XEX and then apply TU2 only at
runtime.

The codegen tool creates a runtime and calls the normal XEX module loader. For
`default.xex`, `UserModule::LoadFromFile` probes the sibling
`default.xexp`, applies the title-update delta, and only then exposes the
loaded module to `BinaryView` / analysis. Therefore a sibling TU2 can change
the image that function discovery actually sees.

GATE 0 validates the known base/TU pair before GATE 1 is allowed to count as a
build result.

## Why seeds are still required

ReXGlue v0.10.0 has several complementary discovery mechanisms:

- direct call / function-graph discovery;
- PDATA/configured functions;
- RTTI vtable scanning;
- jump-table analysis;
- gap filling and explicit tail-call handling.

However, generic function-pointer scanning is disabled upstream because of
false positives, and runtime-computed/vtable targets can still escape static
discovery. Hell's Gate history contains concrete cases where functions were
first discovered only from runtime unresolved dispatches.

The preservation model is therefore:

```text
upstream proven entrypoints
        +
runtime-learned entrypoints
        +
exact XEX+TU static discovery
        =
cumulative manifest
```

No one layer is allowed to erase another.

## Runtime-log learning

`prepare_variant_manifest.py` supports:

```text
python tools/portable_builder/prepare_variant_manifest.py --learn-runtime-log PATH
```

It recognizes both historical "unresolved function" logs and the current
fail-fast `InvalidFunctionTrap` wording. New guest-code targets are appended
to `tools/portable_builder/runtime_function_seeds.txt` and merged into future
manifest resets.

The packaged `LAUNCH_RUN00.cmd` now performs this automatically when the
package is run from inside the repository.

## Automatic audits

### Source / CI audit

`tools/portable_builder/preservation_audit.py --mode source`

Runs without copyrighted game data. It verifies:

- exactly 339 unique upstream seeds;
- the two known RUN00(5) indirect targets are in the ledger;
- the cumulative manifest contains every seed;
- the upstream midasm hook is preserved;
- `InvalidFunctionTrap` remains fail-fast;
- the SDK patch contains no bogus `Subproject commit ...-dirty` gitlink;
- TU2 fiber helper invariants exist;
- builder semantics do not call a compiled executable a runtime PASS.

GitHub Actions runs this audit on `preservation-autofix`.

### Build audit

`tools/portable_builder/preservation_audit.py --mode build`

Additionally requires the validated retail inputs and generated output. Before
packaging, it verifies **all 339 preserved seeds are actually registered**,
that generated direct unresolved traps are zero, and that the generated fiber
patches are present.

### RUN audit

`tools/portable_builder/analyze_run_log.py RUN00.log`

The RUN launcher executes it automatically and writes:

- `logs/RUN00.report.json`
- `logs/RUN00.report.md`

The parser is conservative: absence of an error in a short log is not a PASS.
GATE 2 needs runtime progress plus zero unresolved guest dispatches. GATE 3 is
blocked until GATE 2 passes and is based only on authoritative presenter
readbacks. Captures are scheduled at frames 1, 2, 3, 4, 8, 16, 32, 64, 128,
256 and 512 until a non-zero image appears. Early zero frames are
`INCONCLUSIVE`; zero output through frame 512 is a GATE 3 failure.

RUN reports also contain a `BASELINE-PURITY` subgate. A base-campaign RUN
must show DLC disabled and must not install/mirror DLC or seed a foreign shader
cache.

## Base-campaign isolation

GATE 0-11 deliberately run without DLC contamination:

- `enable_dlc=false` is the default and RUN00 forces it explicitly;
- base state uses `userdata_base` (or LocalAppData `RUN00-base`);
- DLC auto-install is deferred to GATE 12;
- runtime analysis fails the `BASELINE-PURITY` subgate if DLC mutation or
  shader-cache seeding is observed.

Language selection is also data-driven rather than guessed from XEX region
flags. `detect_disc_languages.py` ports upstream's BIGH/VIV manifest parser.
The base RUN chooses English when present, otherwise the first text language
actually declared by the disc, and pairs it with upstream's matching Xbox
country ID. Spanish is language ID 5 / country ID 31, but GATE 10 will only
attempt Spanish when the VIV manifest actually declares ID 5.

## SDK patch reproducibility

The SDK patch previously ended with a gitlink delta from the real libmspack
submodule SHA to the impossible pseudo-revision `<sha>-dirty`. That was an
artifact of materializing POSIX symlink placeholders on Windows, not a real
submodule revision.

The dirty gitlink hunk has been removed. The builder may still materialize
libmspack files locally after resetting submodules; this no longer changes the
patch's declared source revision.

## Upstream divergence policy

Do not blindly copy every current upstream convenience patch into the
preservation baseline.

One intentional divergence is unsupported-language fallback. Current upstream
injects it at the generated label `loc_823C2504`; preservation-autofix leaves
that phase disabled until the equivalent routine can be identified by
signature/structure for this exact TU image.

Conversely, preservation-autofix is stricter than upstream around fibers: a
fresh build fails if setjmp/longjmp functions or required call-site patches are
not detected.

## Validation gates

| Gate | Requirement | Current evidence |
|---|---|---|
| 0 | inputs/hash/TU | Automated; last runtime evidence showed 0.0.0.1 -> 0.0.2.1 |
| 1 | complete codegen | Automated build gate; must register all preserved seeds |
| 2 | zero unresolved guest functions | **Last known RUN00(5): FAIL**; new cumulative strategy awaiting runtime evidence |
| 3 | actual D3D12 presenter output non-zero | BLOCKED by GATE 2; authoritative readback instrumentation ready |
| 4 | intro/menu | UNVERIFIED |
| 5 | input/menu navigation | UNVERIFIED |
| 6 | New Game | UNVERIFIED |
| 7 | first stable gameplay | UNVERIFIED |
| 8 | audio/video sync | UNVERIFIED |
| 9 | checkpoint/save/load | UNVERIFIED |
| 10 | languages | UNVERIFIED |
| 11 | full campaign | UNVERIFIED |
| 12 | TU2/DLC | UNVERIFIED |
| 13 | PC modernization | UNVERIFIED |

Do not advance a gate by assumption. See `PRESERVATION_AUDIT_MATRIX.md` for
the subsystem-level audit.
