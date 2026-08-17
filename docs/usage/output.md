# Output, catalog, and phase

Use high-level `output` for normal stimulus. It verifies ordinary in-range
requests and accepts the instrument's normalization of deliberately wild
frequency/amplitude/offset combinations.

```bash
dg1022 output --channel 1 --waveform sine --frequency 1kHz --amplitude 2Vpp --enable
dg1022 output --channel 2 --waveform square --frequency 5kHz --amplitude 2Vpp --duty 30 --enable
dg1022 differential --waveform dc --offset1 0V --offset2 1V --load INF --enable
```

Apply the requested state directly. Do not add preflight, state snapshots,
automatic shutdown, restoration, or post-checks unless explicitly requested.
Successful control is silent and exits zero. Square duty is normalized to
20–80%; pulse duty is normalized to 0.001–99.999% inside the CLI.
`differential` configures both channels through one USBTMC session; for periodic
waveforms `--phase` is CH2 relative to CH1, while DC uses independent offsets.

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
