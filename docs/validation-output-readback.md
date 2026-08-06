# 2026-07-27 output-readback regression

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
  `../validation/waveforms-output-readback-fix.json`.

The DC function reads back as `CH1:ARB` on this unit; numeric DC registers and
output state still match and are verified. A 360 degree phase request read back
as 180 degrees and was correctly rejected by the new verifier; validated phase
values such as 30 degrees continue to pass.

Focused physical transition results are stored in
`../validation/output-readback-repeat.json`; the 20-cycle register/readback record
is `../validation/output-readback-register-repeat.json`.

Unit test result after repair: 16 passed.
