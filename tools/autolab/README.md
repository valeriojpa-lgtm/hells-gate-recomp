# Dante AutoLab

Portable research harness for the native PC reconstruction work.

## Goal

Reduce the user's local workflow to:

1. Put `DanteAutoLab.exe` beside the user's own extracted game files.
2. Double-click it.
3. Return the generated `Dante_AutoLab_Result` output.

No Python, Visual Studio, CMake, SDK, or installer is required on the user's PC.

## Safety / preservation rules

- AutoLab is read-only against game data unless a stage explicitly documents otherwise.
- It never loads or executes `default.xex`.
- Proprietary game files and extracted assets are not stored in this repository.
- The repository contains only interoperability/research code, metadata, and reproducible contracts.
- Every research stage reports PASS / CHECK / FAIL and must avoid claiming semantics that were not demonstrated.

## Current bootstrap

`DanteAutoLab.c` currently performs a lightweight regression bootstrap:

- validates `bigfile0.viv` and `bigfile1.viv` as BIGH containers;
- re-resolves the known `frontend\\frontend_global.str` resource key;
- detects optional `default.xex` / `default.xexp` without loading them;
- writes one summary under `Dante_AutoLab_Result`;
- records the handoff to the next automated research stage.

The current research frontier is after RUN01/T25:

- T01-T24: frozen contracts;
- T25: corpus cartography completed, exact `OnLoadMovieScreen` upstream owner still unresolved;
- next: deep ActionScript/native/Lua/localization tracing.

## Build

GitHub Actions builds a portable Windows x64 executable automatically whenever AutoLab sources or its workflow change.

The workflow publishes an artifact named:

`DanteAutoLab-Windows-x64`

The generated executable depends only on normal Windows system libraries.

## Local inputs

Required beside the executable:

```text
bigfile0.viv
bigfile1.viv
```

Optional when a later stage needs them:

```text
default.xex
default.xexp
```

DLC is intentionally not required by the bootstrap gate.

## Result handling

AutoLab output is disposable research output and is ignored by Git. Do not commit VIV/XEX/XEXP files, extracted game resources, or AutoLab result dumps.
