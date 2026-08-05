---
name: dg1022-cli
description: Operate, test, debug, or document the RIGOL DG1022 function generator through the public dg1022 CLI, including output, catalog get/set/action, modulation, sweep, burst, counter, arbitrary waveforms, and connected validation. Use for DG1022 hardware work, dg1022 command changes, waveform generation, cross-instrument tests, or deployment; restrict conclusions to DG1022 and exclude firmware updates.
---

# DG1022 CLI

## Establish Context

Resolve the repository as the directory two levels above this Skill's real path. Read `README.md`, `docs/validation.md`, or the official programming guide only when the task needs their detail. For unfamiliar command semantics, inspect only the relevant `dg1022 commands show NAME` entry.

The validated instrument is serial `DG1D124605159`. Treat its `*IDN?` response as authoritative. USB product text may incorrectly say DG3000 or DS1000, and `/dev/usbtmcN` changes between connections.

## Use The Public CLI

Use `dg1022`, preferring the repository's `.venv/bin/dg1022` when present. Select known hardware directly with `--serial DG1D124605159`. Use `list`, `info`, or `config` only when device selection, identity, or configuration is actually unknown or under diagnosis; do not make them routine preflight steps.

Use high-level `output`, `modulate`, `sweep-config`, `burst-config`, `counter`, and `arb` workflows when available. Otherwise use catalog-backed `get`, `set`, and `action`. Use `raw` only when no public typed command exists and after checking the official command catalog.

Do not call transport classes, open `/dev/usbtmcN` directly, or send SCPI through a Python library when a CLI command exists. Do not implement or invoke firmware update, bootloader, or reflash behavior.

For DC output, use the natural `output --waveform dc --offset VALUE` form; the CLI supplies
the positional APPLY placeholders that the instrument ignores. For cross-channel phase, use the
high-level `--phase` path so the CLI performs physical phase alignment.
Treat the `output` result's `readback` object as authoritative. A readback
mismatch is a failed configuration, not a successful stimulus.

## Enforce Output Safety

Before enabling a new stimulus, ensure the requested voltage, offset, load convention, wiring, and receiver limits are safe. Do not add unrelated state queries when those facts are already known. Prefer `INF` load for high-impedance measurement inputs unless the setup explicitly requires termination.

After a task that enabled generator outputs, disable those outputs through the public CLI:

```bash
dg1022 --serial DG1D124605159 set output.enabled OFF --channel 1
dg1022 --serial DG1D124605159 set output.enabled OFF --channel 2
```

Do not require the user to save or restore unrelated generator state, and do not add routine post-cleanup queries. Never leave an output enabled merely to match a historical validation baseline.

## Handle CLI Failures Without Losing The Task

Report every CLI error to the user as soon as it occurs, including the failing command and immediate impact, but do not stop work solely because an error occurred. Keep the requested task as the first priority:

- If the error blocks the task, diagnose it and attempt a repair immediately so the task can continue.
- If the error does not block the task, record enough evidence to reproduce it, finish the requested task first, and then diagnose and attempt a repair.
- After a repair, run focused regression tests plus the repository's required test suite and any safe connected checks needed to establish the fix.
- Every completed, sufficiently verified CLI, test, documentation, or Skill change must be
  committed and pushed to the current branch's configured remote before reporting completion.
  Do not leave finished work only in the local worktree, and do not include unrelated pre-existing
  changes. If pushing fails, report the exact failure rather than presenting the change as fully
  delivered.
- If the repair is incomplete, cannot be pushed, or lacks sufficient testing, continue any remaining feasible task work and explain the error, attempted repair, remaining risk, and missing validation in detail in the final report.

## Verify Changes And Claims

Run `python -m pytest` after code changes. For connected coverage, use `tools/live_acceptance.py` groups instead of ad hoc transport calls and retain its cleanup behavior.

Distinguish command readback from physical measurement. Do not claim calibrated accuracy, bandwidth, flatness, sweep endpoints, or behavior beyond the connected evidence. Use synchronized 8192-point scope records for cross-channel phase; do not use independent 600-point NORMAL transfers.
