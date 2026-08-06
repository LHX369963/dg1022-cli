# Output, catalog, and phase

Use high-level `output` for normal stimulus; it applies and reads back the
requested values. A mismatched `readback` is a failed configuration.

```bash
dg1022 output --channel 1 --waveform sine --frequency 1kHz --amplitude 2Vpp --enable
dg1022 output --channel 2 --waveform sine --frequency 10kHz --amplitude 2Vpp --phase 90 --enable
```

Check voltage, offset, load convention, wiring, and receiver limits before
enabling output. Prefer `INF` load for high-impedance inputs unless termination
is intentional. Disable only outputs enabled by the task; do not snapshot or
restore unrelated generator state.

For typed SCPI, inspect the needed entry then use `get`, `set`, or `action`:

```bash
dg1022 commands show frequency.output
dg1022 get frequency.output --channel 2
dg1022 set voltage.amplitude 2Vpp --channel 1
```

Use `raw` only where no typed command exists; `batch` accepts newline-delimited
SCPI. `--phase` performs the required `PHASe:ALIGN`; phase-register writes alone
are not reliable. Cross-channel phase evidence requires synchronized 8192-point
scope records, not independent 600-point NORMAL transfers.
