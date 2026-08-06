# Modulation, sweep, burst, and counter

These high-level modes configure CH1 and avoid manually assembling SCPI:

```bash
dg1022 modulate am --internal-frequency 1kHz --depth 50 --enable
dg1022 modulate fm --internal-frequency 1kHz --deviation 2kHz --enable
dg1022 sweep-config --start 200Hz --stop 2kHz --time 0.1 --spacing LIN --enable
dg1022 burst-config --mode TRIG --cycles 5 --period 10ms --enable
dg1022 counter --enable
```

Use `dg1022 <command> --help` for mode-specific parameters. The CLI preserves
requested settings; do not assume ideal analog behavior from a successful write.
For example, the tested unit measured about 1.50 Vpp envelope with a 2 Vpp,
50%-depth AM carrier. Treat physical measurement as evidence, not command
readback.

After a task leaves a generator output active, turn off that task's output. Do
not run unrelated configuration checks or restore historical settings.
