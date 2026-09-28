# Q01 — Vanilla Baseline

Goal: prove that the user's preserved Xbox 360 build compiles and boots on the fork before any preservation changes are introduced.

## Frozen source baseline

Upstream commit:

e1991cfef0b8886da752da8a4e1477ff8c3b5c12 (v0.7.2-beta-hotfix)

Working branch:

q01-vanilla-baseline

## Expected local game data

Copyrighted game files remain local and are ignored by Git.

game/
  default.xex
  default.xexp
  bigfile0.viv
  bigfile1.viv
  avatarassetpack       (optional for Q01)
  nxeart                (optional for Q01)
  $systemupdate         (optional for Q01)

Validated preserved build:

- default.xex — 10,760,192 bytes — SHA-256 abfef19fa03a247ab17d5c011e34ca70a0338f13c15b7fd8932c7ff7d9e2c2e9
- default.xexp (TU2) — 2,205,696 bytes — SHA-256 0842733820a27e0c902e6a652b3cd71d2c4a05f36db5121c1d342416a6b7ab09
- bigfile0.viv — 3,176,365,408 bytes
- bigfile1.viv — 2,692,050,613 bytes

The TU2 delta source digest matches this default.xex exactly.

## Why Q01 disables the experimental native renderer

Q01 tests the simplest upstream Windows path first: ReXGlue + Xenos + D3D12. The DiligentCore native renderer remains upstream code and will be tested separately after the baseline is proven.

No game logic, renderer, timing, filesystem or input behavior is modified in Q01.

## Build

From PowerShell at repository root:

    .\scripts\q01_build_windows.ps1

The script:

1. validates the preserved game build,
2. sets up ReXGlue v0.10.0,
3. configures the regular D3D12 path,
4. runs codegen,
5. applies the repository's existing generated-code patches,
6. builds dantes_inferno.exe.

Expected output:

    out/build/win-amd64-release/dantes_inferno.exe

## PASS criteria

Q01 becomes frozen only when all of these pass:

- build completes without gameplay/runtime changes,
- game executable starts,
- TU2 is detected/applied,
- intro/FMVs render,
- main menu is reached,
- new game reaches gameplay,
- save creation succeeds,
- clean exit succeeds.

Any failure is investigated on this branch before Q02 begins.
