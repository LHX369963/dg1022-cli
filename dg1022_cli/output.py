"""High-level DG1022 output and differential-source operations."""

from __future__ import annotations

import argparse
import math
import re
import time

from .catalog import get_command, render_command
from .errors import ProtocolError
from .transport import LinuxUsbtmc


def _parse_number(value: str) -> float | str:
    normalized = re.sub(r"^CH[12]:\s*", "", value.strip(), flags=re.IGNORECASE)
    try:
        number = float(normalized)
    except ValueError:
        return value
    return number if math.isfinite(number) else normalized.lower()


def _parse_quantity(value: str, units: dict[str, float]) -> float:
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z]*)\s*",
        value,
    )
    if not match:
        raise ProtocolError(f"cannot verify numeric output value {value!r}")
    suffix = match.group(2).upper()
    if suffix not in units:
        raise ProtocolError(f"cannot verify output unit {suffix!r} in {value!r}")
    return float(match.group(1)) * units[suffix]


def _close_enough(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-9)


def _output_readback(generator: LinuxUsbtmc, args: argparse.Namespace) -> dict[str, object]:
    suffix = "" if args.channel == 1 else ":CH2"
    waveform_readback = generator.query_text(f"FUNCtion{suffix}?").strip()
    waveform_normalized = re.sub(
        r"^CH[12]:\s*", "", waveform_readback, flags=re.IGNORECASE
    )
    result: dict[str, object] = {"waveform": waveform_readback}
    normalized_request = False
    try:
        if args.frequency is not None and args.waveform != "dc":
            requested_frequency = _parse_quantity(
                args.frequency, {"": 1.0, "HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6}
            )
            maximum_frequency = {
                "sine": 20e6, "square": 5e6, "ramp": 150e3,
                "pulse": 3e6, "noise": math.inf, "user": 5e6,
            }[args.waveform]
            normalized_request |= not 1e-6 <= requested_frequency <= maximum_frequency
        if args.amplitude is not None and args.load is not None:
            requested_amplitude = _parse_quantity(
                args.amplitude, {"": 1.0, "VPP": 1.0, "MVPP": 1e-3, "UVPP": 1e-6}
            )
            requested_offset = _parse_quantity(
                args.offset or "0", {"": 1.0, "V": 1.0, "MV": 1e-3, "UV": 1e-6}
            )
            peak_limit = 10.0 if args.load.strip().upper() in {"INF", "INFINITY"} else 5.0
            normalized_request |= (
                requested_amplitude <= 0
                or requested_amplitude > 2 * peak_limit
                or abs(requested_offset) + requested_amplitude / 2 > peak_limit
            )
    except ProtocolError:
        pass
    waveform_prefixes = {
        "sine": ("SIN",),
        "square": ("SQU",),
        "ramp": ("RAMP",),
        "pulse": ("PULS",),
        "noise": ("NOIS",),
        # This DG1022 implements APPLY:DC through its arbitrary-function path.
        "dc": ("DC", "ARB"),
        "user": ("USER", "ARB"),
    }[args.waveform]
    if not waveform_normalized.upper().startswith(waveform_prefixes):
        raise ProtocolError(
            f"output waveform readback mismatch: requested {args.waveform}, "
            f"got {result['waveform']!r}"
        )
    # DG1022 implements APPLY:DC through ARB and ignores the frequency and
    # amplitude fields required by APPLY's positional syntax.  Do not reject a
    # valid DC request because those two registers retain their previous values.
    if args.frequency is not None and args.waveform != "dc":
        actual = float(_parse_number(generator.query_text(f"FREQuency{suffix}?")))
        expected = _parse_quantity(
            args.frequency, {"": 1.0, "HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6}
        )
        result["frequency_hz"] = actual
        if not normalized_request and not _close_enough(actual, expected):
            raise ProtocolError(
                f"output frequency readback mismatch: requested {expected:g} Hz, got {actual:g} Hz"
            )
    if args.amplitude is not None and args.waveform != "dc":
        unit = generator.query_text(f"VOLTage:UNIT{suffix}?").strip().upper()
        actual = float(_parse_number(generator.query_text(f"VOLTage{suffix}?")))
        expected = _parse_quantity(
            args.amplitude,
            {
                "": 1.0,
                unit: 1.0,
                "VPP": 1.0,
                "MVPP": 1e-3,
                "UVPP": 1e-6,
                "VRMS": 1.0,
                "MVRMS": 1e-3,
                "UVRMS": 1e-6,
                "DBM": 1.0,
            },
        )
        result["amplitude"] = actual
        result["amplitude_unit"] = unit
        if not normalized_request and not _close_enough(actual, expected):
            raise ProtocolError(
                f"output amplitude readback mismatch: requested {expected:g} {unit}, "
                f"got {actual:g} {unit}"
            )
    if args.offset is not None:
        actual = float(_parse_number(generator.query_text(f"VOLTage:OFFSet{suffix}?")))
        expected = _parse_quantity(
            args.offset, {"": 1.0, "V": 1.0, "MV": 1e-3, "UV": 1e-6}
        )
        result["offset_v"] = actual
        if not normalized_request and not _close_enough(actual, expected):
            raise ProtocolError(
                f"output offset readback mismatch: requested {expected:g} V, got {actual:g} V"
            )
    if args.phase is not None:
        actual = float(_parse_number(generator.query_text(f"PHASe{suffix}?")))
        expected = _parse_quantity(args.phase, {"": 1.0, "DEG": 1.0})
        result["phase_deg"] = actual
        phase_error = (actual - expected + 180.0) % 360.0 - 180.0
        if not _close_enough(phase_error, 0.0):
            raise ProtocolError(
                f"output phase readback mismatch: requested {expected:g} deg, got {actual:g} deg"
            )
    if args.load is not None:
        actual = _parse_number(generator.query_text(f"OUTPut:LOAD{suffix}?"))
        result["load"] = actual
        if args.load.strip().upper() in {"INF", "INFINITY"}:
            matches = actual == "infinity"
        else:
            expected = _parse_quantity(args.load, {"": 1.0, "OHM": 1.0})
            matches = isinstance(actual, float) and _close_enough(actual, expected)
        if not matches:
            raise ProtocolError(
                f"output load readback mismatch: requested {args.load!r}, got {actual!r}"
            )
    if args.enable is not None:
        actual = generator.query_text(f"OUTPut{suffix}?").strip().upper()
        expected = "ON" if args.enable else "OFF"
        result["enabled"] = actual
        if actual != expected:
            raise ProtocolError(
                f"output state readback mismatch: requested {expected}, got {actual!r}"
            )
    return result


def _configure_output(generator: LinuxUsbtmc, args: argparse.Namespace) -> dict[str, object]:
    spec = get_command("apply." + args.waveform)
    command = render_command(spec, args.channel)
    suffix = "" if args.channel == 1 else ":CH2"
    restore_enabled = False
    if args.waveform == "dc" and args.enable is None:
        restore_enabled = generator.query_text(f"OUTPut{suffix}?").strip().upper() == "ON"
    frequency = args.frequency
    amplitude = args.amplitude
    if args.waveform == "dc" and args.offset is not None:
        # APPLY parameters are positional even though this instrument ignores
        # the first two for DC.  Supplying harmless placeholders lets the public
        # helper support the natural "--waveform dc --offset ..." form.
        frequency = frequency or "1Hz"
        amplitude = amplitude or "1Vpp"
    values = [value for value in (frequency, amplitude, args.offset) if value is not None]
    if values:
        if frequency is None or (args.offset is not None and amplitude is None):
            raise ProtocolError("APPLy parameters are positional; provide frequency before amplitude/offset")
        command += " " + ",".join(values)
    # APPLY interprets and stores its amplitude using the currently selected
    # load.  Set a requested load first; changing INF to 50 ohm after APPLY
    # makes this DG1022 halve the amplitude register and defeats authoritative
    # readback of the user's requested loaded amplitude.
    if args.load is not None:
        generator.write(f"OUTPut:LOAD{suffix} {args.load}")
    generator.write(command)
    # This unit can occasionally acknowledge APPLY while retaining an earlier
    # parameter when the function/frequency are unchanged. Replay the idempotent
    # command after settling, then require authoritative register readback.
    time.sleep(0.5 if args.waveform == "dc" else 0.3)
    generator.write(command)
    if args.waveform == "dc" and (args.enable is True or restore_enabled):
        generator.write(f"OUTPut{suffix} OFF")
    if args.phase is not None:
        generator.write(f"PHASe{suffix} {args.phase}")
        # APPLY and phase register changes need about one second before ALIGN
        # reliably commits the physical dual-channel relationship on this unit.
        time.sleep(0.9)
        generator.write("PHASe:ALIGN")
        time.sleep(0.3)
        generator.write(f"PHASe{suffix} {args.phase}")
        time.sleep(0.9)
        generator.write("PHASe:ALIGN")
    if args.duty is not None:
        if args.waveform not in {"square", "pulse"}:
            raise ProtocolError("--duty applies only to square or pulse output")
        duty = _parse_quantity(args.duty, {"": 1.0, "PCT": 1.0, "PERCENT": 1.0})
        if args.waveform == "square":
            duty = min(80.0, max(20.0, duty))
            duty_command = render_command(get_command("function.square-duty"), args.channel)
        else:
            duty = min(99.999, max(0.001, duty))
            duty_command = render_command(get_command("pulse.duty"), args.channel)
        generator.write(f"{duty_command} {duty:.12g}")
    if args.enable is not None:
        generator.write(f"OUTPut{suffix} {'ON' if args.enable else 'OFF'}")
        if args.waveform == "dc":
            time.sleep(0.3)
            generator.write(f"OUTPut{suffix} {'ON' if args.enable else 'OFF'}")
    elif restore_enabled:
        generator.write(f"OUTPut{suffix} ON")
    return _output_readback(generator, args)


def _configure_differential(generator: LinuxUsbtmc, args: argparse.Namespace) -> None:
    for channel, offset, phase in (
        (1, args.offset1, "0"),
        (2, args.offset2, args.phase),
    ):
        _configure_output(generator, argparse.Namespace(
            channel=channel,
            waveform=args.waveform,
            frequency=args.frequency,
            amplitude=args.amplitude,
            offset=offset,
            phase=None if args.waveform == "dc" else phase,
            duty=args.duty,
            load=args.load,
            enable=args.enable,
        ))


