---
name: dg1022-cli
description: Operate, test, debug, or document the RIGOL DG1022 function generator through the public dg1022 CLI, including output, catalog get/set/action, modulation, sweep, burst, counter, arbitrary waveforms, and connected validation. Use for DG1022 hardware work, dg1022 command changes, waveform generation, cross-instrument tests, or deployment; restrict conclusions to DG1022 and exclude firmware updates.
---

# DG1022 CLI

## Establish Context

Resolve the repository as the directory two levels above this Skill's real path. Read `README.md` before operating the generator and `docs/validation.md` before making coverage claims. For command semantics, inspect `dg1022 commands show NAME`; consult `docs/official/DG1000_ProgrammingGuide_EN.pdf` when the catalog or device behavior is unclear.

The validated instrument is serial `DG1D124605159`. Treat its `*IDN?` response as authoritative. USB product text may incorrectly say DG3000 or DS1000, and `/dev/usbtmcN` changes between connections.

## Use The Public CLI

Use `dg1022`, preferring the repository's `.venv/bin/dg1022` when present. Select hardware with `--serial DG1D124605159` for connected work. Start with:

```bash
dg1022 list
dg1022 --serial DG1D124605159 info
dg1022 --serial DG1D124605159 config
```

Use high-level `output`, `modulate`, `sweep-config`, `burst-config`, `counter`, and `arb` workflows when available. Otherwise use catalog-backed `get`, `set`, and `action`. Use `raw` only when no public typed command exists and after checking the official command catalog.

Do not call transport classes, open `/dev/usbtmcN` directly, or send SCPI through a Python library when a CLI command exists. Do not implement or invoke firmware update, bootloader, or reflash behavior.

For DC output, use `output --waveform dc` and retain the required frequency/amplitude placeholders described by the CLI. For cross-channel phase, use the high-level `--phase` path so the CLI performs physical phase alignment.

## Enforce Output Safety

Before automated stimulus, confirm identity, both output states, load settings, wiring, and the receiving instrument's safe range. Prefer `INF` load for high-impedance measurement inputs unless the setup explicitly requires termination.

Wrap connected tests in cleanup that always executes these public CLI operations:

```bash
dg1022 --serial DG1D124605159 set output.enabled OFF --channel 1
dg1022 --serial DG1D124605159 set output.enabled OFF --channel 2
dg1022 --serial DG1D124605159 set output.load INFinity --channel 1
dg1022 --serial DG1D124605159 set output.load INFinity --channel 2
```

Verify cleanup with `get output.enabled`, `get output.load`, and `get system.error`. Never leave output enabled merely to match a historical validation baseline.

## Handle CLI Failures Without Losing The Task

Report every CLI error to the user as soon as it occurs, including the failing command and immediate impact, but do not stop work solely because an error occurred. Keep the requested task as the first priority:

- If the error blocks the task, diagnose it and attempt a repair immediately so the task can continue.
- If the error does not block the task, record enough evidence to reproduce it, finish the requested task first, and then diagnose and attempt a repair.
- After a repair, run focused regression tests plus the repository's required test suite and any safe connected checks needed to establish the fix.
- When the repair is complete and sufficiently verified, commit only the repair-related changes and push that commit to the current repository remote. Do not include unrelated pre-existing worktree changes.
- If the repair is incomplete, cannot be pushed, or lacks sufficient testing, continue any remaining feasible task work and explain the error, attempted repair, remaining risk, and missing validation in detail in the final report.

## Verify Changes And Claims

Run `python -m pytest` after code changes. For connected coverage, use `tools/live_acceptance.py` groups instead of ad hoc transport calls and retain its cleanup behavior.

Distinguish command readback from physical measurement. Do not claim calibrated accuracy, bandwidth, flatness, sweep endpoints, or behavior beyond the connected evidence. Use synchronized 8192-point scope records for cross-channel phase; do not use independent 600-point NORMAL transfers.
