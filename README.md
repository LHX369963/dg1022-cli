# RIGOL DG1022 CLI

A dependency-free Linux USBTMC command-line client for the RIGOL DG1022. It
offers a typed programming-guide catalog plus practical workflows for both output
channels, modulation, sweep, burst, counter, and arbitrary waveforms.

The implementation is tested on:

```text
RIGOL TECHNOLOGIES,DG1022,DG1D124605159,00.02.00.06.00.02.07
```

## Coverage

- All 21 command subsystems in the DG1000 programming guide
- 106 merged catalog entries representing 214 channel/query/write operations
- `list`, `info`, `config`, `commands`, `get`, `set`, `action`, `raw`, and
  `batch` workflows
- High-level `output`, `modulate`, `sweep-config`, `burst-config`, and `counter`
  workflows
- Arbitrary waveform upload, selection, catalog, delete, and BIN/CSV/JSON download
- Automatic selection of a single attached instrument with a `DG...` serial

Firmware update is deliberately out of scope. There is no update, bootloader, or
device-reflash command in this project.

## Install

Linux with Python 3.10 or newer and the kernel `usbtmc` driver is required.

```bash
git clone https://github.com/LHX369963/dg1022.git
cd dg1022
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

Install the udev rule once so normal CLI use does not require `sudo`:

```bash
sudo install -m 0644 udev/99-rigol-dg1022-usbtmc.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb
```

Then reconnect the USB cable, or log out and back in if group membership changed.
The rule grants access through `plugdev` and desktop `uaccess`. Running the CLI
itself with `sudo` is neither required nor recommended.

## Use

```bash
dg1022 list
dg1022 info
dg1022 config

dg1022 commands list
dg1022 commands list --section coupling
dg1022 commands show frequency.output
dg1022 get frequency.output --channel 2
dg1022 set voltage.amplitude 2Vpp --channel 1

dg1022 output --channel 1 --waveform sine --frequency 1kHz --amplitude 2Vpp --offset 0V --enable
dg1022 output --channel 2 --waveform sine --frequency 2kHz --amplitude 2Vpp --offset 0V --enable
dg1022 output --channel 2 --waveform sine --frequency 10kHz --amplitude 2Vpp --phase 90 --enable

dg1022 modulate am --internal-frequency 1kHz --depth 50 --enable
dg1022 modulate fm --internal-frequency 1kHz --deviation 2kHz --enable
dg1022 sweep-config --start 200Hz --stop 2kHz --time 0.1 --spacing LIN --enable
dg1022 burst-config --mode TRIG --cycles 5 --period 10ms --enable
dg1022 counter --enable

dg1022 arb upload samples.txt --name TEST_WAVE --select
dg1022 arb list
dg1022 arb download TEST_WAVE --format csv --output test-wave.csv
dg1022 arb delete TEST_WAVE

dg1022 raw 'SYSTem:CLKSRC?'
dg1022 batch commands.scpi
```

Use `--device /dev/usbtmcN` or `--serial SERIAL` when explicit selection is
needed. Unit suffixes accepted by the instrument can be used in high-level values.

When `output --phase` is supplied, the helper sends `PHASe:ALIGN` after writing
the phase and allowing the unit time to finish waveform reconfiguration. Physical
testing showed that writing the phase register alone does not deterministically
apply the dual-channel relationship. Using the scope's 8192-point synchronized
record, commanded 30 and 90 degree relationships measured approximately 30.6 and
89.5 degrees. The scope's 600-point `NORMAL` waveform transfers are not reliably
sample-aligned between channels and must not be used for cross-channel phase work.

## DG1022 Compatibility Notes

- Do not issue `USBTMC_IOCTL_EOM_ENABLE` to this instrument; reads time out after
  that ioctl. The transport intentionally omits it.
- Queries wait 2 ms before reading. Ordinary writes wait 100 ms so a later USB
  clear cannot interrupt a command still being processed. Both are configurable.
- CH2 pulse duty uses the abbreviation `PULSe:DCYC:CH2` required by this unit.
- Nonvolatile arbitrary-waveform copy succeeds as `DATA:COPY name`; the optional
  `VOLATILE` source documented by the guide is omitted for this unit.
- `DATA:LOAD` is handled as the unit's three-command transfer: header, raw 16-bit
  payload, then a no-response state reset.
- Channel coupling settings read and write correctly. On this unit, later SCPI
  frequency writes do not make the other channel follow dynamically; do not treat
  coupling as a software frequency tracker.
- With 2 Vpp carrier and 50% AM depth, the measured overall envelope was about
  1.50 Vpp. The CLI preserves the requested settings and does not compensate for
  this unit-specific amplitude behavior.

## Verification

```bash
python -m pytest
```

The checked-in official references are:

- `docs/official/DG1000_ProgrammingGuide_EN.pdf`
- `docs/official/DG1000_UserGuide_EN.pdf`

See `docs/validation.md` for the live command audit and cross-instrument results.

The command catalog follows the programming guide. The tested scope connection is
DG CH1 to DS1152E CH1 and DG CH2 to DS1152E CH2.
