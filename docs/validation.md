# DG1022 Validation

Validation date: 2026-07-19

## Instrument

```text
RIGOL TECHNOLOGIES,DG1022,DG1D124605159,00.02.00.06.00.02.07
/dev/usbtmc3
```

The device node above records that validation session only. Linux assigns the
`/dev/usbtmcN` suffix dynamically; the same generator was subsequently enumerated
as `/dev/usbtmc2`. A changed suffix is not evidence that the DG1022 is offline.
Use `dg1022 list` to locate it and `dg1022 info` to verify a successful `*IDN?`
exchange, or select it by serial number instead of hard-coding the node.

The physical connection was DG CH1 to DS1152E CH1 and DG CH2 to DS1152E CH2.

## Catalog And Transport

- 21/21 programming-guide subsystems represented
- 106 merged catalog entries
- 214 operations after expanding channel and query/write variants
- 98 live query instances audited; 95 returned directly
- Empty nonvolatile catalog and unnamed memory-slot responses account for two
  device-state-dependent cases
- CH2 pulse duty required `PULSe:DCYC:CH2`; that rendering is modeled explicitly

Original-value query-set writeback produced 66 direct passes from 82 instances.
The other 16 were internal parameters of disabled AM/FM/PM/FSK/sweep/burst modes.
After enabling each owning mode, all six mode families wrote and read back correctly.

The transport omits `USBTMC_IOCTL_EOM_ENABLE`, which makes this instrument time
out. It uses 2 ms query delay and 100 ms ordinary command delay. High-level phase
configuration adds a device-specific settling interval before `PHASe:ALIGN`.

## Functional Checks

- APPLy sine/square/ramp/pulse/noise/DC/user: 7 waveforms x 2 channels passed
- AM/FM/PM/FSK, linear sweep, and 5-cycle burst observed on the DS1152E
- Counter enable/query/disable passed
- Display, clock, language, remote/lock/local, memory slots, phase align, channel
  copy, and coupling register operations passed
- Arbitrary data lifecycle passed: upload, VOLATILE, 4096-point expansion, copy,
  catalog/free-space, rename, download, and delete
- Repeated arbitrary BIN/CSV/JSON download passed using the three-command
  `DATA:LOAD` state machine
- CH1-to-CH2 copy preserved ramp, 1234 Hz, 1.5 Vpp, 0.2 V offset, and 30 degree
  phase settings

Cross-channel phase must be measured from the scope's 8192-point `MAXIMUM` record.
The 600-point `NORMAL` transfers are not reliably aligned between channels. The
high-level phase path measured 60.4 degrees for a 60 degree command; separate 30
and 90 degree checks measured approximately 30.6 and 89.5 degrees.

Channel coupling parameters read and write correctly, but later SCPI frequency
writes do not dynamically move the other channel on this instrument. Coupling is
not claimed as a software frequency tracker.

## Representative Measurements

```text
Square duty: CH1 25% -> 24.8%, CH2 75% -> 75.0%
Pulse duty:  CH1 20% -> 20.0%, CH2 60% -> 60.3%
DC level:    +0.5 V -> +0.496 V, -0.5 V -> -0.521 V
FM:          about 7.6 to 12.2 kHz for 10 kHz +/- 2 kHz
FSK:         about 5.0 kHz and 10.0 kHz clusters
Burst:       five positive-going crossings per complete burst
Sweep:       repeating 200 Hz to 2 kHz linear sweep over 0.1 s
```

## Detailed Connected Acceptance

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

Machine-readable results are in `validation/*.json`. The robustness report also
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

## 2026-07-27 Output Readback Regression

An AD817 module test exposed a silent high-level stimulus discrepancy. CH1 was
already configured for 1 kHz sine at 0.1 Vpp with its output disabled. An
`output` invocation requested the same function/frequency at 1 Vpp and returned
success, but the synchronized scope input remained about 0.1 Vpp. A later
frequency change committed 1 Vpp normally. The intermittent ignore could not be
reproduced in five immediate pre-fix cycles, but the historical command and
scope records establish that the old success response was not authoritative.

The `output` helper now replays `APPLy` after settling and verifies all requested
registers. A unit regression proves that stale amplitude readback causes a
nonzero exit, and the full unit suite passes 16/16.

Connected verification on serial `DG1D124605159` included:

- 20 same-function/same-frequency 0.1-to-1 Vpp transitions with matching
  frequency, amplitude and output-state readback;
- 10 additional transitions observed physically through DS1152E CH1, measuring
  0.960 to 0.976 Vpp at the loaded module input in all 10 cases;
- successful sine 1 kHz/1 Vpp/30 degree and DC -0.5 V high-level readback;
- the standard-waveform connected group, where all 64 CH1 cases passed. The
  group total was 66 pass, 14 fail and 48 error because the user fixture routed
  DG CH1 through the DUT and did not connect DG CH2 to DS CH2; its 62 CH2 cases
  are not applicable to this wiring and are retained in
  `validation/waveforms-output-readback-fix.json`.

The DC function reads back as `CH1:ARB` on this unit; numeric DC registers and
output state still match and are verified. A 360 degree phase request read back
as 180 degrees and was correctly rejected by the new verifier; validated phase
values such as 30 degrees continue to pass.

Focused physical transition results are stored in
`validation/output-readback-repeat.json`; the 20-cycle register/readback record
is `validation/output-readback-register-repeat.json`.

Unit test result after repair: 16 passed.
