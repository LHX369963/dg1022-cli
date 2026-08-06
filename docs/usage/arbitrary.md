# Arbitrary waveforms

Upload whitespace- or comma-separated samples, optionally select the result,
and download/delete named entries:

```bash
dg1022 arb upload samples.txt --name TEST_WAVE --select
dg1022 arb list
dg1022 arb download TEST_WAVE --format csv --output test-wave.csv
dg1022 arb delete TEST_WAVE
```

`DATA:LOAD` uses the unit's required header, 16-bit payload, then no-response
state-reset transfer. Persistent copy on the tested unit is `DATA:COPY name`;
the optional documented `VOLATILE` source is intentionally not sent.

`APPLy:DC` reports as `ARB` on this instrument. The high-level output verifier
accepts that alias only for DC/USER while still requiring the numeric registers
and output state to match.
