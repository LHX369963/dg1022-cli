---
name: dg1022-cli
description: Control the connected RIGOL DG1022 with the dg1022 CLI.
---

# DG1022 CLI

Use `dg1022/.venv/bin/dg1022 --serial DG1D124605159` from the instrument-cli
workspace. Execute the requested operation
directly; do not inspect, preserve, restore, or clean up unrelated state.

Common forms:

```bash
dg1022/.venv/bin/dg1022 --serial DG1D124605159 output --channel 1 --waveform sine --frequency 1kHz --amplitude 1Vpp --offset 0V --load INF --enable
dg1022/.venv/bin/dg1022 --serial DG1D124605159 output --channel 2 --waveform square --frequency 5kHz --amplitude 2Vpp --offset=-0.3V --duty 30 --load INF --enable
dg1022/.venv/bin/dg1022 --serial DG1D124605159 modulate fm --source INT --internal-waveform SIN --internal-frequency 1kHz --deviation 10kHz --enable
dg1022/.venv/bin/dg1022 --serial DG1D124605159 sweep-config --start 1kHz --stop 10kHz --time 1s --spacing LIN --enable
dg1022/.venv/bin/dg1022 --serial DG1D124605159 burst-config --mode TRIG --cycles 10 --period 20ms --trigger-source IMM --enable
dg1022/.venv/bin/dg1022 --serial DG1D124605159 get frequency.output --channel 1
dg1022/.venv/bin/dg1022 --serial DG1D124605159 set voltage.amplitude 2Vpp --channel 1
```

Prefer `output`, `modulate`, `sweep-config`, `burst-config`, `counter`, and
`arb`; use typed `get`/`set`/`action` next. Use `commands show <name>` only for
an unfamiliar typed command and `raw` only when no maintained command exists.
