# Functional checks and representative measurements

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
