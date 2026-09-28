# DANTE'S INFERNO — PRESERVATION AUTOFIX

This branch is the cumulative preservation/debug branch built on top of
florinp93/hells-gate-recomp and ReXGlue v0.10.0.

## Why it exists

RUN00(5) proved the title update loads and the D3D12 renderer presents, but the
guest framebuffer remains zero while runtime dispatch repeatedly reaches guest
functions that were not registered.

The previous Q01 "minimal manifest" strategy was therefore wrong for this
title: it removed upstream indirect function seeds that static direct-call
closure cannot rediscover.

## Current policy

1. Never mask an unresolved guest function by returning from it. Fail fast.
2. Preserve the upstream manifest's proven indirect entrypoints.
3. Add direct targets discovered from the exact user XEX automatically.
4. Learn additional runtime targets from logs instead of asking the user to
   edit manifests.
5. Delete/regenerate codegen deterministically and patch it before compiling.
6. Audit critical generated targets before packaging.
7. Keep user game data out of Git.

## Proven preserved retail inputs

- Title ID: 454108CF
- Media ID: 49028C6A
- base default.xex: 0.0.0.1
- TU2 default.xexp: 0.0.2.1
- default.xex SHA-256:
  abfef19fa03a247ab17d5c011e34ca70a0338f13c15b7fd8932c7ff7d9e2c2e9
- default.xexp SHA-256:
  0842733820a27e0c902e6a652b3cd71d2c4a05f36db5121c1d342416a6b7ab09

## RUN00(5) finding

Two runtime targets dominate the failure:
- 0x825D2C30
- 0x8236E3C0

Both were already present in the upstream Hell's Gate manifest. The adaptive
minimal-manifest reset discarded them, explaining why the executable compiled
but runtime dispatch could not resolve them.

The same log shows VdSwap is reached at 1280x720 while every sampled
SwapGuest frontbuffer block is zero. Treat VFETCH-OOB warnings as secondary
until guest execution is complete; do not patch rendering around missing guest
functions.

## Runtime-log learner

The manifest helper supports:

    python tools/portable_builder/prepare_variant_manifest.py --learn-runtime-log PATH

New title-image unresolved targets are persisted to
tools/portable_builder/runtime_function_seeds.txt and merged into future
manifest resets.

## Next audit gates

- zero unresolved guest dispatches during boot
- non-zero guest framebuffer samples
- intro/menu transition
- input/menu navigation
- new game and first gameplay checkpoint
- audio/video synchronization
- save/load
- language selection
- DLC/TU2 only after base campaign is stable

Do not claim full playability until those gates have evidence.
