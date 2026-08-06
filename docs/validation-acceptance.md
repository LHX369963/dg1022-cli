# Connected acceptance and final baseline

The connected acceptance suite in `tools/live_acceptance.py` was expanded beyond
the catalog audit. It preserves the fixed DG CH1 -> DS CH1 and DG CH2 -> DS CH2
wiring and restores the baseline in a `finally` block.

- 128 standard-waveform cases: 4 functions x 2 channels x 4 frequencies x 4 amplitudes
- 42 level/shape cases: DC, sine offset, square/pulse duty, ramp symmetry, and noise
- 9 AM, 9 FM, 9 PM, and 9 FSK parameter combinations
- 6 linear/log sweep ranges and 8 burst cycle/period combinations
- 6 synchronized 8192-point phase checks from -90 through 180 degrees
- output polarity/load, coupling registers, channel copy, and four ARB lifecycles
- ARB inputs include normalized and DAC encodings at 4, 17, 257, and 4096 points;
  each lifecycle verifies BIN, CSV, and JSON downloads and deletion

The suite found and corrected four device-facing timing issues: modulation
configuration is replayed after enabling a mode, physical phase ALIGN is replayed,
large DATA commands receive length-dependent settling time, and DATA:LOAD retries
once in a fresh USBTMC session after a transport timeout. Sweep endpoint accuracy
is not claimed: long records alias the highest cases, so physical validation checks
that frequency changes while exact start/stop/spacing settings are verified by
generator readback.

Machine-readable results are in `../validation/*.json`. The robustness report also
covers repeated sessions, batch operation, invalid inputs, and numeric formats.

At 2 Vpp carrier and 50% AM depth, this instrument produced an overall envelope
of about 1.50 Vpp. This is recorded as instrument behavior rather than corrected
in software.

## Final Connected Baseline

```text
CH1: sine, 1 kHz, 2 Vpp, 0 V offset, output ON, load INF
CH2: sine, 2 kHz, 2 Vpp, 0 V offset, output ON, load INF
AM/FM/PM/FSK/sweep/burst/coupling: OFF
DS measurement CH1: 1.000 kHz, 2.04 Vpp
DS measurement CH2: 1.980 kHz, 2.02 Vpp
```

Unit test result: 15 passed.
