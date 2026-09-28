# CAMPAIGN REGRESSION WATCHLIST

This file tracks public upstream reports that may matter once the preservation
branch reaches campaign validation. An open GitHub issue is **not** treated as
proof of a bug in preservation-autofix; each item needs reproduction on the
canonical retail XEX + TU2 and an unmodified asset set.

## Priority A — reproducible campaign behavior

### Upstream issue #26 — crash after death near the Gates of Hell

- State upstream: open.
- Reported behavior: dying in front of the Gates of Hell, then entering the
  loading screen, can crash.
- Reporter said they could not reproduce it in earlier/later areas.
- Public comments mention repeated "Too few processor cores - scheduling will
  be wonky" messages, but that alone does not establish causality.
- Public attachment could not be retrieved through the normal GitHub API/web
  route during this audit, so its log has **not** been analyzed here.

Preservation validation:
- Do not test until GATE 7 is stable.
- When campaign testing reaches this point, preserve the complete runtime log
  across death -> reload.
- Classify unresolved guest dispatch, access violation, fiber/save activity,
  filesystem errors and shader/renderer progress separately.
- A pass requires successful death/reload, not merely reaching the location.

## Priority B — rendering correctness

### Upstream issue #65 — Lucifer model rendering under Vulkan

- State upstream: open.
- Reported against v0.7.2-beta using Vulkan.
- Upstream requested logs; no confirmed root cause is documented in the public
  issue at audit time.

Preservation validation:
- D3D12/Xenos baseline remains the reference until GATE 11.
- Do not let a Vulkan-only report contaminate the D3D12 campaign gate.
- Once modern/native renderer work starts, compare the same cutscene between
  D3D12/Xenos and Vulkan with matching game data.

## Priority C — pacing / external limiter interactions

### Upstream issue #61 — v0.7 performance regression

- State upstream: open.
- Reports nominal 60 FPS with poor perceived frame pacing/stutter.

### Upstream issue #66 — external limiter interaction / post-save black screen

- State upstream: open.
- Report includes simultaneous external FPS limiting and a system-level crash,
  plus a later in-game black screen after the first save.
- The external limiter portion is not a clean preservation reproduction.

Preservation validation:
- Baseline RUNs should use only the project's own 60 Hz pacing.
- External overlays/limiters are excluded from GATE 0-12 reproduction.
- The post-save black-screen claim becomes relevant only if it reproduces
  without external tools.

## Priority D — environment robustness

### Upstream issue #69 — Program Files logging crash

- State upstream: open.
- Public WinDbg stack points through `std::filesystem::_Throw_fs_error` and
  `rex::InitLogging`.
- Same install reportedly works after copying it out of Program Files.

Preservation action:
- Fixed proactively in preservation-autofix:
  - default logs use `user_data_root/logs`;
  - logging directory creation uses non-throwing filesystem APIs;
  - file-sink creation failure is reported and no longer aborts the game;
  - RUN00 probes its portable directory and falls back to
    `%LOCALAPPDATA%\HellsGatePreservation\RUN00` when necessary.

This remains unverified on real Windows protected-directory execution.

## Excluded / contaminated reports

### Upstream issue #67 — missing saves/statues/Lucifer

The reporter later stated that reinstalling fixed it and identified a downloaded
translation as the underlying problem. Do not treat this as evidence against
the clean retail preservation baseline.

## Gate mapping

| Watch item | Earliest relevant gate | What constitutes evidence |
|---|---:|---|
| #26 death/reload crash | GATE 7 / GATE 9 | clean death -> reload sequence and full log |
| #65 Lucifer render | GATE 11 then 13 | same scene, clean data, renderer A/B |
| #61 pacing | GATE 13 | frametime evidence after campaign stability |
| #66 post-save black | GATE 9 | reproduction without external limiter/overlay |
| #69 Program Files | robustness pre-GATE 4 | protected-path launch succeeds or fails with explicit recoverable error |

The watchlist should be revised as upstream issues close or gain a confirmed
root cause, but historical entries must not be silently removed.
