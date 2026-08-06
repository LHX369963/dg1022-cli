---
name: dg1022-cli
description: Operate, test, debug, or document the RIGOL DG1022 function generator through the public dg1022 CLI, including output, catalog get/set/action, modulation, sweep, burst, counter, arbitrary waveforms, and connected validation. Use for DG1022 hardware work, dg1022 command changes, waveform generation, cross-instrument tests, or deployment; restrict conclusions to DG1022 and exclude firmware updates.
---

# DG1022 CLI

Resolve the repository two levels above this file's real path. Use its
`.venv/bin/dg1022` when present, otherwise `dg1022`; use only the public CLI.
The supported unit is DG1022, validated as `DG1D124605159`; do not infer other
models or modify firmware.

Select known hardware with `--serial DG1D124605159` (preferred) or a known
`--device`; do not scan first. Use `list`, `info`, or `config` only when
selection, identity, or configuration is genuinely unknown. Do not open USBTMC
or send Python-library SCPI when a CLI command exists.

Use high-level `output`, `modulate`, `sweep-config`, `burst-config`, `counter`,
and `arb` first; use typed `get`/`set`/`action` next and `raw` only as a last
resort. Read [output](../../docs/usage/output.md),
[modes](../../docs/usage/modes.md), or
[arbitrary waveforms](../../docs/usage/arbitrary.md) only for that operation;
inspect a catalog entry only when its semantics are unfamiliar.

Before enabling output, verify requested voltage, offset, load, wiring, and
receiver limits. Prefer `INF` for high-impedance inputs. Stop only outputs
started by the task; do not require state snapshots, restoration, or routine
post-checks. A high-level output `readback` mismatch is failure.

Normal transport does not CLEAR. On failure, report the command and impact,
then diagnose without abandoning the requested task. For code or connected
validation work, read [development](../../docs/usage/development.md);
acceptance is not daily-use preflight. Run the test suite after code changes and
keep evidence distinct from claims of physical accuracy.
