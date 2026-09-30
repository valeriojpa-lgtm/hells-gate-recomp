# Dante AutoLab Progress

This file tracks the portable AutoLab work separately from the main port.

## Current state

- [x] GitHub working branch: `chatgpt/dante-autolab-bootstrap`
- [x] Portable no-CRT Win64 bootstrap in `tools/autolab/`
- [x] Research contracts recorded through T25
- [x] GitHub Actions Windows build fixed and passing
- [x] Artifact emitted as `DanteAutoLab-Windows-x64`
- [x] Local workflow target: double-click EXE, then return one result bundle
- [ ] T26 deep upstream tracer
- [ ] Nested ActionScript call-graph traversal
- [ ] Lua/native/localization fallback tracing
- [ ] One-click automatic result ZIP
- [ ] Full frozen-contract regression chain

## Research frontier

T24 is frozen: the terms APX assignment API and `_parent.OnLoadMovieScreen(1)` handoff are proven.

T25 is CHECK: the frontend APX corpus is mapped, but no exact upstream `DefineFunction OnLoadMovieScreen` owner is proven yet.

T26 will automate the next search cascade:

`nested ActionScript -> caller graph -> Lua/native resources -> localization provider -> terms setters`

## Preservation rules

- Never commit proprietary game data.
- AutoLab remains read-only against user-owned game files.
- Do not execute or redistribute `default.xex`.
- Only freeze semantics that are directly demonstrated.
- User-facing builds remain portable: no Python/.NET/Visual Studio/CMake requirement.