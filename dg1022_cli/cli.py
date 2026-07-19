from __future__ import annotations

import argparse
import csv
import json
import math
import re
import struct
import sys
import time
from pathlib import Path
from typing import Sequence

from .catalog import COMMANDS, CommandSpec, get_command, render_command
from .errors import Dg1022Error, ProtocolError, TransportError
from .transport import LinuxUsbtmc, choose_device, discover_devices


SNAPSHOT_COMMANDS = {
    "channel1_function": "FUNCtion?",
    "channel1_frequency_hz": "FREQuency?",
    "channel1_amplitude": "VOLTage?",
    "channel1_amplitude_unit": "VOLTage:UNIT?",
    "channel1_offset_v": "VOLTage:OFFSet?",
    "channel1_phase_deg": "PHASe?",
    "channel1_output": "OUTPut?",
    "channel1_load_ohm": "OUTPut:LOAD?",
    "channel2_function": "FUNCtion:CH2?",
    "channel2_frequency_hz": "FREQuency:CH2?",
    "channel2_amplitude": "VOLTage:CH2?",
    "channel2_amplitude_unit": "VOLTage:UNIT:CH2?",
    "channel2_offset_v": "VOLTage:OFFSet:CH2?",
    "channel2_phase_deg": "PHASe:CH2?",
    "channel2_output": "OUTPut:CH2?",
    "channel2_load_ohm": "OUTPut:LOAD:CH2?",
    "am": "AM:STATe?",
    "fm": "FM:STATe?",
    "pm": "PM:STATe?",
    "fsk": "FSK:STATe?",
    "sweep": "SWEep:STATe?",
    "burst": "BURSt:STATe?",
    "coupling": "COUPling?",
}

_NEGATIVE_VALUE_PREFIX = "__DG1022_NEGATIVE_VALUE__"


def _protect_negative_unit_values(argv: Sequence[str]) -> list[str]:
    """Keep argparse from treating values such as -0.5V as option flags."""
    pattern = re.compile(r"^-\d+(?:\.\d*)?(?:[eE][+-]?\d+)?[A-Za-z]+$")
    return [_NEGATIVE_VALUE_PREFIX + value if pattern.fullmatch(value) else value for value in argv]


def _restore_negative_unit_values(args: argparse.Namespace) -> None:
    for name, value in vars(args).items():
        if isinstance(value, str) and value.startswith(_NEGATIVE_VALUE_PREFIX):
            setattr(args, name, value.removeprefix(_NEGATIVE_VALUE_PREFIX))
        elif isinstance(value, list):
            setattr(args, name, [
                item.removeprefix(_NEGATIVE_VALUE_PREFIX)
                if isinstance(item, str) and item.startswith(_NEGATIVE_VALUE_PREFIX) else item
                for item in value
            ])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dg1022", description="RIGOL DG1022 USBTMC CLI")
    parser.add_argument("--device", help="USBTMC node, for example /dev/usbtmc3")
    parser.add_argument("--serial", help="select a generator by serial number")
    parser.add_argument("--timeout-ms", type=int, default=5000, help="USBTMC timeout (default: 5000)")
    parser.add_argument("--query-delay-ms", type=float, default=2.0, help="delay before query reads (default: 2 ms)")
    parser.add_argument("--command-delay-ms", type=float, default=100.0, help="DG1022 processing delay after writes (default: 100 ms)")
    parser.add_argument("--no-clear", action="store_true", help="do not clear the USBTMC session on open")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list attached RIGOL USBTMC devices")
    sub.add_parser("info", help="query generator identity")
    sub.add_parser("config", help="query both channels and active operating modes")

    commands = sub.add_parser("commands", help="browse the official programming-guide command catalog")
    commands_sub = commands.add_subparsers(dest="commands_command", required=True)
    commands_list = commands_sub.add_parser("list")
    commands_list.add_argument("--section")
    commands_show = commands_sub.add_parser("show")
    commands_show.add_argument("name")

    for operation in ("get", "set", "action"):
        item = sub.add_parser(operation, help=f"{operation} a command from the official manual catalog")
        item.add_argument("name")
        item.add_argument("values", nargs="*", help="SCPI parameter values")
        item.add_argument("--channel", type=int, choices=(1, 2))

    raw = sub.add_parser("raw", help="send an arbitrary SCPI command")
    raw.add_argument("scpi", help="complete SCPI command without a newline")
    raw.add_argument("--read", action="store_true", help="read one response after writing")
    raw.add_argument("--binary", action="store_true", help="write response bytes to --output/stdout")
    raw.add_argument("--output", type=Path)
    raw.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024)

    batch = sub.add_parser("batch", help="run newline-delimited SCPI; query lines are printed")
    batch.add_argument("file", type=Path, help="command file, or - for stdin")

    output = sub.add_parser("output", help="configure a channel waveform and optionally enable its output")
    output.add_argument("--channel", type=int, choices=(1, 2), required=True)
    output.add_argument("--waveform", choices=("sine", "square", "ramp", "pulse", "noise", "dc", "user"), required=True)
    output.add_argument("--frequency", help="frequency with optional unit, e.g. 10kHz")
    output.add_argument("--amplitude", help="amplitude with optional unit, e.g. 2.5Vpp")
    output.add_argument("--offset", help="DC offset with optional unit")
    output.add_argument("--phase", help="initial phase in degrees")
    output.add_argument("--load", help="load in ohms or INF")
    output.add_argument("--enable", action=argparse.BooleanOptionalAction, default=None)

    modulate = sub.add_parser("modulate", help="configure AM, FM, PM, or FSK on CH1")
    modulate.add_argument("mode", choices=("am", "fm", "pm", "fsk"))
    modulate.add_argument("--source", choices=("INT", "EXT"), default="INT")
    modulate.add_argument("--internal-waveform", choices=("SIN", "SQU", "RAMP", "NRAM", "TRI", "NOIS", "USER"))
    modulate.add_argument("--internal-frequency")
    modulate.add_argument("--depth", help="AM depth in percent")
    modulate.add_argument("--deviation", help="FM frequency or PM phase deviation")
    modulate.add_argument("--hop-frequency", help="FSK alternate frequency")
    modulate.add_argument("--rate", help="internal FSK rate")
    modulate.add_argument("--enable", action=argparse.BooleanOptionalAction, default=True)

    sweep_config = sub.add_parser("sweep-config", help="configure CH1 frequency sweep")
    sweep_config.add_argument("--start")
    sweep_config.add_argument("--stop")
    sweep_config.add_argument("--time")
    sweep_config.add_argument("--spacing", choices=("LIN", "LOG"))
    sweep_config.add_argument("--trigger-source", choices=("IMM", "EXT", "BUS"))
    sweep_config.add_argument("--enable", action=argparse.BooleanOptionalAction, default=True)

    burst_config = sub.add_parser("burst-config", help="configure CH1 burst output")
    burst_config.add_argument("--mode", choices=("TRIG", "GAT"))
    burst_config.add_argument("--cycles")
    burst_config.add_argument("--period")
    burst_config.add_argument("--phase")
    burst_config.add_argument("--gate-polarity", choices=("NORM", "INV"))
    burst_config.add_argument("--trigger-source", choices=("IMM", "EXT", "BUS"))
    burst_config.add_argument("--enable", action=argparse.BooleanOptionalAction, default=True)

    counter = sub.add_parser("counter", help="query the hardware counter")
    counter.add_argument("--enable", action=argparse.BooleanOptionalAction, default=None)

    arb = sub.add_parser("arb", help="upload or manage arbitrary waveforms")
    arb_sub = arb.add_subparsers(dest="arb_command", required=True)
    upload = arb_sub.add_parser("upload", help="upload comma/whitespace-delimited samples to VOLATILE")
    upload.add_argument("file", type=Path)
    upload.add_argument("--dac", action="store_true", help="input values are integer DAC codes 0..16383")
    upload.add_argument("--name", help="also copy to nonvolatile memory (1 letter plus up to 11 letters/digits/underscores)")
    upload.add_argument("--select", action="store_true", help="select uploaded waveform on CH1")
    upload.add_argument("--enable", action="store_true", help="enable CH1 output after upload")
    arb_sub.add_parser("list", help="list all available arbitrary waveforms")
    delete = arb_sub.add_parser("delete", help="delete an arbitrary waveform")
    delete.add_argument("name")
    download = arb_sub.add_parser("download", help="download a waveform using the DG1022 two-stage transfer")
    download.add_argument("name", nargs="?", default="VOLATILE")
    download.add_argument("--format", choices=("bin", "csv", "json"), default="bin")
    download.add_argument("--output", type=Path, required=True)

    return parser


def _session(args: argparse.Namespace) -> LinuxUsbtmc:
    return LinuxUsbtmc(
        choose_device(args.device, args.serial),
        timeout_ms=args.timeout_ms,
        clear_on_open=not args.no_clear,
        query_delay_ms=args.query_delay_ms,
        command_delay_ms=args.command_delay_ms,
    )


def _parse_number(value: str) -> float | str:
    normalized = re.sub(r"^CH[12]:\s*", "", value.strip(), flags=re.IGNORECASE)
    try:
        number = float(normalized)
    except ValueError:
        return value
    return number if math.isfinite(number) else normalized.lower()


def _identity_dict(identity: str, device: str) -> dict[str, str]:
    fields = [field.strip() for field in identity.split(",")]
    version = next((field for field in reversed(fields[3:]) if field), "")
    return {
        "manufacturer": fields[0] if fields else "",
        "model": fields[1] if len(fields) > 1 else "",
        "serial": fields[2] if len(fields) > 2 else "",
        "software_version": version,
        "device": device,
    }


def _query_snapshot(generator: LinuxUsbtmc) -> dict[str, object]:
    result: dict[str, object] = {"identity": generator.query_text("*IDN?")}
    for name, command in SNAPSHOT_COMMANDS.items():
        result[name] = _parse_number(generator.query_text(command))
    return result


def _join_values(spec: CommandSpec, values: list[str]) -> str:
    if not values:
        return ""
    joined = " ".join(values)
    if spec.value_style == "colon":
        return ":" + joined.lstrip(":")
    return " " + joined


def _settle_after_write(command: str) -> None:
    upper = command.upper()
    if upper.startswith("DATA:COPY"):
        time.sleep(2.0)
    elif upper.startswith(("DATA:RENAME", "DATA:DELETE")):
        time.sleep(0.5)
    elif upper == "DATA" or upper.startswith(("DATA ", "DATA:DAC")):
        time.sleep(min(10.0, 0.5 + len(command) / 3_000.0))


def _run_batch(generator: LinuxUsbtmc, lines) -> int:
    for line_number, raw_line in enumerate(lines, start=1):
        command = raw_line.strip()
        if not command or command.startswith("#"):
            continue
        if "?" in command.split(" ", 1)[0]:
            print(generator.query_text(command))
        else:
            generator.write(command)
    return 0


def _configure_output(generator: LinuxUsbtmc, args: argparse.Namespace) -> None:
    spec = get_command("apply." + args.waveform)
    command = render_command(spec, args.channel)
    suffix = "" if args.channel == 1 else ":CH2"
    restore_enabled = False
    if args.waveform == "dc" and args.enable is None:
        restore_enabled = generator.query_text(f"OUTPut{suffix}?").strip().upper() == "ON"
    values = [value for value in (args.frequency, args.amplitude, args.offset) if value is not None]
    if values:
        if args.frequency is None or (args.offset is not None and args.amplitude is None):
            raise ProtocolError("APPLy parameters are positional; provide frequency before amplitude/offset")
        command += " " + ",".join(values)
    generator.write(command)
    if args.waveform == "dc":
        # This unit can update the DC registers without committing the physical
        # level. Repeating the idempotent APPLY after settling commits it without
        # briefly disabling an already-enabled output.
        time.sleep(0.5)
        generator.write(command)
        if args.enable is True or restore_enabled:
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
    if args.load is not None:
        generator.write(f"OUTPut:LOAD{suffix} {args.load}")
    if args.enable is not None:
        generator.write(f"OUTPut{suffix} {'ON' if args.enable else 'OFF'}")
    elif restore_enabled:
        generator.write(f"OUTPut{suffix} ON")


def _configure_mode(generator: LinuxUsbtmc, args: argparse.Namespace) -> dict[str, str]:
    mode = args.mode.upper()
    options = {
        "internal-waveform": args.internal_waveform,
        "internal-frequency": args.internal_frequency,
        "depth": args.depth,
        "deviation": args.deviation,
        "hop-frequency": args.hop_frequency,
        "rate": args.rate,
    }
    allowed = {
        "AM": {"internal-waveform", "internal-frequency", "depth"},
        "FM": {"internal-waveform", "internal-frequency", "deviation"},
        "PM": {"internal-waveform", "internal-frequency", "deviation"},
        "FSK": {"hop-frequency", "rate"},
    }[mode]
    invalid = [name for name, value in options.items() if value is not None and name not in allowed]
    if invalid:
        raise ProtocolError(f"{args.mode} does not support --{invalid[0]}")
    has_parameters = any(value is not None for value in options.values()) or args.source is not None
    if has_parameters:
        generator.write(f"{mode}:STATe ON")
        commands = [f"{mode}:SOURce {args.source}"]
        if args.internal_waveform:
            commands.append(f"{mode}:INTernal:FUNCtion {args.internal_waveform}")
        if args.internal_frequency:
            commands.append(f"{mode}:INTernal:FREQuency {args.internal_frequency}")
        if args.depth:
            commands.append(f"AM:DEPTh {args.depth}")
        if args.deviation:
            commands.append(f"{mode}:DEViation {args.deviation}")
        if args.hop_frequency:
            commands.append(f"FSK:FREQuency {args.hop_frequency}")
        if args.rate:
            commands.append(f"FSK:INTernal:RATE {args.rate}")
        for command in commands:
            generator.write(command)
        # The first parameter update immediately after enabling a modulation
        # family is occasionally ignored by this unit. Replaying the idempotent
        # configuration after it settles makes the high-level operation atomic.
        time.sleep(0.3)
        for command in commands:
            generator.write(command)
    generator.write(f"{mode}:STATe {'ON' if args.enable else 'OFF'}")
    return {"mode": mode, "state": "ON" if args.enable else "OFF"}


def _configure_sweep(generator: LinuxUsbtmc, args: argparse.Namespace) -> dict[str, str]:
    generator.write("SWEep:STATe ON")
    for command, value in (("FREQuency:STARt", args.start), ("FREQuency:STOP", args.stop),
                           ("SWEep:TIME", args.time), ("SWEep:SPACing", args.spacing),
                           ("TRIGger:SOURce", args.trigger_source)):
        if value is not None:
            generator.write(f"{command} {value}")
    generator.write(f"SWEep:STATe {'ON' if args.enable else 'OFF'}")
    return {"mode": "SWEEP", "state": "ON" if args.enable else "OFF"}


def _configure_burst(generator: LinuxUsbtmc, args: argparse.Namespace) -> dict[str, str]:
    generator.write("BURSt:STATe ON")
    for command, value in (("BURSt:MODE", args.mode), ("BURSt:NCYCles", args.cycles),
                           ("BURSt:INTernal:PERiod", args.period), ("BURSt:PHASe", args.phase),
                           ("BURSt:GATE:POLarity", args.gate_polarity),
                           ("TRIGger:SOURce", args.trigger_source)):
        if value is not None:
            generator.write(f"{command} {value}")
    generator.write(f"BURSt:STATe {'ON' if args.enable else 'OFF'}")
    return {"mode": "BURST", "state": "ON" if args.enable else "OFF"}


def _query_counter(generator: LinuxUsbtmc, enabled: bool | None) -> dict[str, object]:
    if enabled is not None:
        generator.write(f"COUNter {'ON' if enabled else 'OFF'}")
    commands = {
        "coupling": "COUNter:COUPling?", "sensitivity": "COUNter:SENSitivity?",
        "trigger_level": "COUNter:TLEVel?", "high_frequency_reject": "COUNter:HFRS?",
        "frequency_hz": "COUNter:FREQuency?", "period_seconds": "COUNter:PERiod?",
        "duty_percent": "COUNter:DCYCle?", "positive_width_seconds": "COUNter:POSWidth?",
        "negative_width_seconds": "COUNter:NEGWidth?",
    }
    return {name: _parse_number(generator.query_text(command)) for name, command in commands.items()}


def _load_samples(path: Path, dac: bool) -> list[str]:
    try:
        text = path.read_text()
    except OSError as exc:
        raise ProtocolError(f"cannot read samples from {path}: {exc}") from exc
    tokens = [token for token in re.split(r"[\s,;]+", text.strip()) if token]
    if not 1 <= len(tokens) <= 524_288:
        raise ProtocolError("an arbitrary waveform requires 1..524288 samples")
    result: list[str] = []
    for index, token in enumerate(tokens):
        try:
            value = int(token) if dac else float(token)
        except ValueError as exc:
            raise ProtocolError(f"sample {index} is not numeric: {token!r}") from exc
        if dac and not 0 <= value <= 16383:
            raise ProtocolError(f"DAC sample {index} is outside 0..16383")
        if not dac and not -1.0 <= value <= 1.0:
            raise ProtocolError(f"normalized sample {index} is outside -1..1")
        result.append(str(value))
    return result


def _validate_arb_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,11}", name):
        raise ProtocolError("waveform name must match [A-Za-z][A-Za-z0-9_]{0,11}")


def _run_arb(generator: LinuxUsbtmc, args: argparse.Namespace) -> int:
    if args.arb_command == "list":
        print(generator.query_text("DATA:CATalog?"))
        return 0
    if args.arb_command == "delete":
        _validate_arb_name(args.name)
        command = f"DATA:DELete {args.name}"
        generator.write(command)
        _settle_after_write(command)
        return 0
    if args.arb_command == "download":
        if args.name.upper() != "VOLATILE":
            _validate_arb_name(args.name)
        command = f"DATA:LOAD {args.name}"
        def transfer() -> tuple[int, bytes]:
            generator.write(command)
            time.sleep(0.5)
            try:
                header = generator.read(max_bytes=256).decode("ascii").strip()
            except UnicodeDecodeError as exc:
                raise ProtocolError("DATA:LOAD returned a binary header") from exc
            match = re.fullmatch(r"ArbData,HEADER,(\d+)", header)
            if not match:
                raise ProtocolError(f"unexpected DATA:LOAD header: {header!r}")
            points = int(match.group(1))
            generator.write(command)
            time.sleep(0.5)
            payload = generator.read(max_bytes=points * 2 + 16)
            if len(payload) != points * 2:
                raise ProtocolError(f"DATA:LOAD returned {len(payload)} bytes for {points} points")
            generator.write(command)
            time.sleep(0.5)
            return points, payload

        try:
            points, payload = transfer()
        except TransportError:
            generator.close()
            time.sleep(0.5)
            generator.__enter__()
            points, payload = transfer()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        values = struct.unpack(f"<{points}H", payload)
        if args.format == "bin":
            args.output.write_bytes(payload)
        elif args.format == "json":
            args.output.write_text(json.dumps({"name": args.name, "points": points, "raw_u16": values}))
        else:
            with args.output.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("index", "raw_u16", "raw_i16"))
                writer.writerows((index, value, value if value < 32768 else value - 65536)
                                 for index, value in enumerate(values))
        print(json.dumps({"name": args.name, "points": points, "format": args.format, "output": str(args.output)}))
        return 0
    samples = _load_samples(args.file, args.dac)
    upload_command = ("DATA:DAC" if args.dac else "DATA") + " VOLATILE," + ",".join(samples)
    generator.write(upload_command)
    _settle_after_write(upload_command)
    if args.name:
        _validate_arb_name(args.name)
        # This DG1022 only completes COPY when the optional source is omitted.
        copy_command = f"DATA:COPY {args.name}"
        generator.write(copy_command)
        _settle_after_write(copy_command)
    if args.select:
        generator.write(f"FUNCtion:USER {args.name or 'VOLATILE'}")
        generator.write("FUNCtion USER")
    if args.enable:
        generator.write("OUTPut ON")
    print(json.dumps({"points": len(samples), "encoding": "dac" if args.dac else "normalized", "name": args.name or "VOLATILE"}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(_protect_negative_unit_values(raw_argv))
    _restore_negative_unit_values(args)
    try:
        if args.command == "list":
            for item in discover_devices():
                marker = " generator" if item.serial.upper().startswith("DG") else ""
                print(f"{item.path} usb={item.vendor_id}:{item.product_id} serial={item.serial or '-'} product={item.product or '-'}{marker}")
            return 0
        if args.command == "commands":
            if args.commands_command == "list":
                for spec in COMMANDS:
                    if args.section and spec.section != args.section:
                        continue
                    print(f"{spec.name:38} {spec.kind:9} {spec.command}")
                return 0
            spec = get_command(args.name)
            print(json.dumps(spec.__dict__, indent=2))
            return 0
        if args.command in {"get", "set", "action"}:
            spec = get_command(args.name)
            command = render_command(spec, args.channel)
            if args.command == "get":
                if not spec.can_query:
                    raise ProtocolError(f"{spec.name} is not queryable")
                with _session(args) as generator:
                    print(generator.query_text(command + "?" + _join_values(spec, args.values)))
                return 0
            if args.command == "set":
                if not spec.can_write or spec.kind == "action":
                    raise ProtocolError(f"{spec.name} is not settable")
                if not args.values:
                    raise ProtocolError("set requires at least one value")
                with _session(args) as generator:
                    wire_command = command + _join_values(spec, args.values)
                    generator.write(wire_command)
                    _settle_after_write(wire_command)
                return 0
            if spec.kind != "action":
                raise ProtocolError(f"{spec.name} is not an action")
            if args.values:
                raise ProtocolError("action does not accept values")
            with _session(args) as generator:
                generator.write(command)
            return 0

        with _session(args) as generator:
            if args.command == "info":
                print(json.dumps(_identity_dict(generator.query_text("*IDN?"), str(generator.device.path)), indent=2))
                return 0
            if args.command == "config":
                print(json.dumps(_query_snapshot(generator), indent=2))
                return 0
            if args.command == "raw":
                should_read = args.read or "?" in args.scpi.split(" ", 1)[0]
                if should_read:
                    data = generator.query(args.scpi, max_bytes=args.max_bytes)
                    if args.output:
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_bytes(data)
                    elif args.binary:
                        sys.stdout.buffer.write(data)
                    else:
                        print(data.decode("ascii").strip())
                else:
                    generator.write(args.scpi)
                return 0
            if args.command == "batch":
                if str(args.file) == "-":
                    return _run_batch(generator, sys.stdin)
                try:
                    with args.file.open() as stream:
                        return _run_batch(generator, stream)
                except OSError as exc:
                    raise ProtocolError(f"cannot read batch file {args.file}: {exc}") from exc
            if args.command == "output":
                _configure_output(generator, args)
                print(json.dumps({
                    "channel": args.channel,
                    "waveform": args.waveform,
                    "frequency": args.frequency,
                    "amplitude": args.amplitude,
                    "offset": args.offset,
                    "phase": args.phase,
                    "load": args.load,
                    "enabled": args.enable,
                }))
                return 0
            if args.command == "modulate":
                print(json.dumps(_configure_mode(generator, args)))
                return 0
            if args.command == "sweep-config":
                print(json.dumps(_configure_sweep(generator, args)))
                return 0
            if args.command == "burst-config":
                print(json.dumps(_configure_burst(generator, args)))
                return 0
            if args.command == "counter":
                print(json.dumps(_query_counter(generator, args.enable), indent=2))
                return 0
            if args.command == "arb":
                return _run_arb(generator, args)
        parser.error(f"unsupported command combination: {args.command}")
        return 2
    except (Dg1022Error, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
