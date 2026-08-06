# RIGOL DG1022 CLI

Linux USBTMC command-line client for the RIGOL DG1022. It covers both output
channels, catalog SCPI, modulation, sweep, burst, counter, and arbitrary
waveforms. It is tested with `DG1D124605159`; firmware update/reflash is out of
scope.

## Install

Requires Linux, Python 3.10+, and kernel `usbtmc`:

```bash
git clone https://github.com/LHX369963/dg1022-cli.git && cd dg1022-cli
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e '.[test]'
sudo install -m 0644 udev/99-rigol-dg1022-usbtmc.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=usb
```

Reconnect once after installing the rule. Normal use does not need `sudo`.

## Quick use

```bash
dg1022 --serial DG1D124605159 output --channel 1 --waveform sine \
  --frequency 1kHz --amplitude 2Vpp --offset 0V --enable
# Stop the output created by this task when finished.
dg1022 --serial DG1D124605159 set output.enabled OFF --channel 1
```

A known `--serial` or `--device /dev/usbtmcN` is used directly; do not run
`list`, `info`, or `config` first. Use them only to diagnose unknown selection,
identity, or configuration. `/dev/usbtmcN` is not stable across reconnection;
prefer the serial selector in scripts.

## Topics

- [Output, catalog, and phase](docs/usage/output.md)
- [Modulation, sweep, burst, and counter](docs/usage/modes.md)
- [Arbitrary waveforms](docs/usage/arbitrary.md)
- [Compatibility, development, and evidence](docs/usage/development.md)

The Codex Skill is [`skills/dg1022-cli`](skills/dg1022-cli). Command parameters
are authoritative in `dg1022 <command> --help`; official manuals are in
`docs/official/`.
