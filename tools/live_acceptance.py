#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DS_ROOT = ROOT.parent / "ds1152e"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DS_ROOT))

from dg1022_cli.transport import LinuxUsbtmc as Generator  # noqa: E402
from dg1022_cli.transport import choose_device as choose_generator  # noqa: E402
from rigol_cli.transport import LinuxUsbtmc as Scope  # noqa: E402
from rigol_cli.transport import choose_device as choose_scope  # noqa: E402
from rigol_cli.waveform import parse_ieee_block  # noqa: E402


FREQUENCIES = (100.0, 1_000.0, 10_000.0, 100_000.0)
AMPLITUDES = (0.5, 1.0, 2.0, 4.0)
WAVEFORMS = ("SINusoid", "SQUare", "RAMP", "PULSe")


@dataclass
class CaseResult:
    group: str
    name: str
    status: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    checks: dict[str, bool]
    error: str | None = None


class Recorder:
    def __init__(self) -> None:
        self.results: list[CaseResult] = []

    def case(
        self,
        group: str,
        name: str,
        expected: dict[str, Any],
        run: Callable[[], tuple[dict[str, Any], dict[str, bool]]],
    ) -> None:
        try:
            observed, checks = run()
            status = "pass" if checks and all(checks.values()) else "fail"
            result = CaseResult(group, name, status, expected, observed, checks)
        except Exception as exc:
            result = CaseResult(group, name, "error", expected, {}, {}, str(exc))
        self.results.append(result)
        if result.status != "pass":
            print(f"{result.status.upper():5} {group}/{name}: {result.error or result.checks}", flush=True)

    def write(self, path: Path, started: float) -> None:
        counts = {state: sum(item.status == state for item in self.results) for state in ("pass", "fail", "error")}
        payload = {
            "started_at_unix": started,
            "duration_seconds": round(time.time() - started, 3),
            "counts": counts,
            "results": [asdict(item) for item in self.results],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps({"output": str(path), **counts, "total": len(self.results)}), flush=True)


def _number(value: str) -> float:
    value = value.strip()
    if value.upper().startswith("CH2:"):
        value = value.split(":", 1)[1].strip()
    result = float(value)
    if not math.isfinite(result) or abs(result) >= 9e37:
        raise ValueError(f"unavailable numeric response: {value}")
    return result


def _write_all(device: Generator | Scope, commands: list[str], extra_delay: float = 0.0) -> None:
    for command in commands:
        device.write(command)
        if extra_delay:
            time.sleep(extra_delay)


def _dg_suffix(channel: int) -> str:
    return "" if channel == 1 else ":CH2"


def _scope_source(channel: int) -> str:
    return f"CHANnel{channel}"


def _scope_scale(amplitude: float) -> float:
    return {0.5: 0.1, 1.0: 0.2, 2.0: 0.5, 4.0: 1.0}[amplitude]


def _time_scale(frequency: float) -> float:
    return 0.2 / frequency


def _decimal(value: float) -> str:
    return f"{value:.12f}".rstrip("0").rstrip(".")


def configure_scope(scope: Scope, channel: int, frequency: float, amplitude: float, trigger_level: float = 0.0) -> None:
    source = _scope_source(channel)
    _write_all(scope, [
        ":CHANnel1:DISPlay ON",
        ":CHANnel2:DISPlay ON",
        f":CHANnel{channel}:COUPling DC",
        f":CHANnel{channel}:PROBe 1",
        f":CHANnel{channel}:INVert OFF",
        f":CHANnel{channel}:OFFSet 0",
        f":CHANnel{channel}:SCALe {_scope_scale(amplitude)}",
        f":TIMebase:SCALe {_decimal(_time_scale(frequency))}",
        ":TRIGger:MODE EDGE",
        f":TRIGger:EDGE:SOURce {source}",
        ":TRIGger:EDGE:SLOPe POSitive",
        f":TRIGger:EDGE:LEVel {trigger_level}",
        ":TRIGger:EDGE:SWEep AUTO",
        ":WAVeform:POINts:MODE MAXimum",
        ":RUN",
    ], extra_delay=0.015)
    time.sleep(0.35)


def measure(scope: Scope, channel: int, *metrics: str) -> dict[str, float]:
    source = _scope_source(channel)
    return {metric: _number(scope.query_text(f":MEASure:{metric}? {source}")) for metric in metrics}


def capture(scope: Scope, channel: int, mode: str = "NORMal") -> list[float]:
    scope.write(":STOP")
    time.sleep(0.12)
    scope.write(f":WAVeform:POINts:MODE {mode}")
    time.sleep(0.03)
    raw = parse_ieee_block(scope.query(f":WAVeform:DATA? {_scope_source(channel)}"))
    scale = _number(scope.query_text(f":CHANnel{channel}:SCALe?"))
    offset = _number(scope.query_text(f":CHANnel{channel}:OFFSet?"))
    scope.write(":WAVeform:POINts:MODE MAXimum")
    scope.write(":RUN")
    return [(125 - value) * scale / 25.0 - offset for value in raw]


def capture_pair(scope: Scope) -> tuple[list[float], list[float]]:
    scope.write(":STOP")
    time.sleep(0.15)
    scope.write(":WAVeform:POINts:MODE MAXimum")
    raw1 = parse_ieee_block(scope.query(":WAVeform:DATA? CHANnel1"))
    raw2 = parse_ieee_block(scope.query(":WAVeform:DATA? CHANnel2"))
    scale1 = _number(scope.query_text(":CHANnel1:SCALe?"))
    scale2 = _number(scope.query_text(":CHANnel2:SCALe?"))
    offset1 = _number(scope.query_text(":CHANnel1:OFFSet?"))
    offset2 = _number(scope.query_text(":CHANnel2:OFFSet?"))
    scope.write(":RUN")
    return (
        [(125 - value) * scale1 / 25.0 - offset1 for value in raw1],
        [(125 - value) * scale2 / 25.0 - offset2 for value in raw2],
    )


def _cli(executable: str, *args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        (executable, *args), cwd=cwd, text=True, capture_output=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError(f"{executable} {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _cli_failure(executable: str, *args: str, cwd: Path = ROOT) -> tuple[int, str]:
    result = subprocess.run(
        (executable, *args), cwd=cwd, text=True, capture_output=True, timeout=30,
    )
    return result.returncode, result.stderr.strip()


def _dg_cli(generator: Generator, *args: str) -> str:
    generator.close()
    try:
        return _cli("dg1022", *args)
    finally:
        generator.__enter__()


def _scope_cli(scope: Scope, *args: str) -> str:
    scope.close()
    try:
        return _cli("rigol", *args, cwd=DS_ROOT)
    finally:
        scope.__enter__()


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))]


def _local_rms(samples: list[float], window: int) -> list[float]:
    window = max(2, min(window, len(samples)))
    squares = [value * value for value in samples]
    total = sum(squares[:window])
    result = [math.sqrt(total / window)]
    for index in range(window, len(samples)):
        total += squares[index] - squares[index - window]
        result.append(math.sqrt(max(0.0, total / window)))
    return result


def _crossing_frequencies(samples: list[float], sample_rate: float) -> list[float]:
    if len(samples) < 3:
        return []
    midpoint = statistics.median(samples)
    crossings: list[float] = []
    for index in range(1, len(samples)):
        if samples[index - 1] < midpoint <= samples[index]:
            crossings.append(float(index))
    dt = 1.0 / sample_rate
    return [1.0 / ((right - left) * dt) for left, right in zip(crossings, crossings[1:]) if right > left]


def _fundamental_phase(samples: list[float], frequency: float, sample_rate: float) -> float:
    dt = 1.0 / sample_rate
    center = statistics.mean(samples)
    value = sum(
        (sample - center) * complex(math.cos(-2 * math.pi * frequency * index * dt),
                                    math.sin(-2 * math.pi * frequency * index * dt))
        for index, sample in enumerate(samples)
    )
    return math.degrees(math.atan2(value.imag, value.real))


def _tone_amplitude(samples: list[float], frequency: float, sample_rate: float) -> float:
    center = statistics.mean(samples)
    value = sum(
        (sample - center) * complex(math.cos(-2 * math.pi * frequency * index / sample_rate),
                                    math.sin(-2 * math.pi * frequency * index / sample_rate))
        for index, sample in enumerate(samples)
    )
    return abs(value) * 2.0 / len(samples)


def apply_wave(generator: Generator, channel: int, waveform: str, frequency: float, amplitude: float, offset: float = 0.0) -> None:
    suffix = _dg_suffix(channel)
    generator.write(f"APPLy:{waveform}{suffix} {frequency},{amplitude},{offset}")
    time.sleep(0.25)
    generator.write(f"OUTPut{suffix} ON")
    time.sleep(0.25)


def restore_baseline() -> None:
    with Generator(choose_generator(), command_delay_ms=150) as generator:
        _write_all(generator, [
            "AM:STATe OFF", "FM:STATe OFF", "PM:STATe OFF", "FSK:STATe OFF",
            "SWEep:STATe OFF", "BURSt:STATe OFF", "COUPling OFF",
            "APPLy:SINusoid 1000,2,0", "PHASe 0",
            "APPLy:SINusoid:CH2 2000,2,0", "PHASe:CH2 0",
        ])
        time.sleep(0.9)
        _write_all(generator, [
            "PHASe:ALIGN", "OUTPut:LOAD INFinity", "OUTPut:LOAD:CH2 INFinity",
            "OUTPut:POLarity NORMal", "OUTPut:POLarity:CH2 NORMal",
            "OUTPut ON", "OUTPut:CH2 ON",
        ])
    with Scope(choose_scope()) as scope:
        _write_all(scope, [
            ":ACQuire:TYPE NORMal", ":ACQuire:MODE RTIM", ":ACQuire:MEMDepth NORMal",
            ":CHANnel1:DISPlay ON", ":CHANnel2:DISPlay ON",
            ":CHANnel1:COUPling DC", ":CHANnel2:COUPling DC",
            ":CHANnel1:PROBe 1", ":CHANnel2:PROBe 1",
            ":CHANnel1:INVert OFF", ":CHANnel2:INVert OFF",
            ":CHANnel1:BWLimit OFF", ":CHANnel2:BWLimit OFF",
            ":CHANnel1:SCALe 0.5", ":CHANnel2:SCALe 0.5",
            ":CHANnel1:OFFSet 0", ":CHANnel2:OFFSet 0",
            ":TIMebase:MODE MAIN", ":TIMebase:FORMat YT", ":TIMebase:SCALe 0.0002",
            ":TIMebase:OFFSet 0", ":TRIGger:MODE EDGE",
            ":TRIGger:EDGE:SOURce CHANnel1", ":TRIGger:EDGE:SLOPe POSitive",
            ":TRIGger:EDGE:LEVel 0", ":TRIGger:EDGE:SWEep AUTO",
            ":MATH:DISPlay OFF", ":FFT:DISPlay OFF",
            ":WAVeform:POINts:MODE MAXimum", ":RUN",
        ], extra_delay=0.015)


def waveform_grid(recorder: Recorder) -> None:
    group = "dg-standard-waveforms"
    with Generator(choose_generator(), command_delay_ms=100) as generator, Scope(choose_scope()) as scope:
        _write_all(generator, ["AM:STATe OFF", "FM:STATe OFF", "PM:STATe OFF", "FSK:STATe OFF", "SWEep:STATe OFF", "BURSt:STATe OFF", "COUPling OFF"])
        shape_ranges = {
            "SINusoid": (0.28, 0.43),
            "SQUare": (0.42, 0.58),
            "RAMP": (0.22, 0.38),
            "PULSe": (0.42, 0.58),
        }
        for channel in (1, 2):
            suffix = _dg_suffix(channel)
            for waveform in WAVEFORMS:
                for frequency in FREQUENCIES:
                    for amplitude in AMPLITUDES:
                        name = f"ch{channel}-{waveform.lower()}-{frequency:g}hz-{amplitude:g}vpp"
                        expected = {"channel": channel, "waveform": waveform, "frequency_hz": frequency, "vpp": amplitude}

                        def run(channel=channel, suffix=suffix, waveform=waveform, frequency=frequency, amplitude=amplitude):
                            apply_wave(generator, channel, waveform, frequency, amplitude)
                            configure_scope(scope, channel, frequency, amplitude)
                            observed = measure(scope, channel, "FREQuency", "VPP", "VRMS")
                            observed["dg_function"] = generator.query_text(f"FUNCtion{suffix}?")
                            observed["dg_frequency_hz"] = _number(generator.query_text(f"FREQuency{suffix}?"))
                            observed["dg_amplitude_vpp"] = _number(generator.query_text(f"VOLTage{suffix}?"))
                            ratio = observed["VRMS"] / observed["VPP"]
                            observed["vrms_vpp_ratio"] = ratio
                            low, high = shape_ranges[waveform]
                            checks = {
                                "function": waveform[:3].upper() in observed["dg_function"].upper(),
                                "dg_frequency": math.isclose(observed["dg_frequency_hz"], frequency, rel_tol=0.001),
                                "dg_amplitude": math.isclose(observed["dg_amplitude_vpp"], amplitude, rel_tol=0.01),
                                "scope_frequency": math.isclose(observed["FREQuency"], frequency, rel_tol=0.06),
                                "scope_vpp": math.isclose(observed["VPP"], amplitude, rel_tol=0.18, abs_tol=0.08),
                                "shape_factor": low <= ratio <= high,
                            }
                            return observed, checks

                        recorder.case(group, name, expected, run)


def level_and_shape_grid(recorder: Recorder) -> None:
    with Generator(choose_generator(), command_delay_ms=100) as generator, Scope(choose_scope()) as scope:
        _write_all(generator, ["AM:STATe OFF", "FM:STATe OFF", "PM:STATe OFF", "FSK:STATe OFF", "SWEep:STATe OFF", "BURSt:STATe OFF", "COUPling OFF"])
        for channel in (1, 2):
            suffix = _dg_suffix(channel)
            for level in (-1.0, -0.5, 0.0, 0.5, 1.0):
                expected = {"channel": channel, "dc_volts": level}

                def run(channel=channel, suffix=suffix, level=level):
                    command = f"APPLy:DC{suffix} 1000,1,{level}"
                    # DC state transitions are most reliable after a USBTMC clear,
                    # which matches one normal CLI invocation per configuration.
                    generator.close()
                    try:
                        with Generator(choose_generator(), command_delay_ms=100) as fresh:
                            fresh.write(command)
                            time.sleep(0.5)
                            fresh.write(command)
                            fresh.write(f"OUTPut{suffix} OFF")
                            time.sleep(0.2)
                            fresh.write(f"OUTPut{suffix} ON")
                            time.sleep(0.8)
                            configure_scope(scope, channel, 1_000, 2.0, trigger_level=level)
                            scope.write(":DISPlay:CLEar")
                            scope.write(":RUN")
                            time.sleep(1.0)
                            observed = measure(scope, channel, "VAVerage")
                            observed["dg_offset"] = _number(fresh.query_text(f"VOLTage:OFFSet{suffix}?"))
                            return observed, {
                                "dg_offset": math.isclose(observed["dg_offset"], level, abs_tol=0.01),
                                "scope_average": math.isclose(observed["VAVerage"], level, abs_tol=0.12),
                            }
                    finally:
                        generator.__enter__()

                recorder.case("dg-dc-levels", f"ch{channel}-{level:+g}v", expected, run)

            for offset in (-0.5, 0.0, 0.5):
                expected = {"channel": channel, "frequency_hz": 1_000, "vpp": 2.0, "offset": offset}

                def run(channel=channel, suffix=suffix, offset=offset):
                    apply_wave(generator, channel, "SINusoid", 1_000, 2.0, offset)
                    configure_scope(scope, channel, 1_000, 2.0, trigger_level=offset)
                    observed = measure(scope, channel, "VPP", "VAVerage", "FREQuency")
                    return observed, {
                        "frequency": math.isclose(observed["FREQuency"], 1_000, rel_tol=0.05),
                        "vpp": math.isclose(observed["VPP"], 2.0, rel_tol=0.15),
                        "average": math.isclose(observed["VAVerage"], offset, abs_tol=0.12),
                    }

                recorder.case("dg-offsets", f"ch{channel}-{offset:+g}v", expected, run)

            for duty in (20.0, 50.0, 80.0):
                for waveform, command in (("SQUare", "FUNCtion:SQUare:DCYCle"), ("PULSe", "PULSe:DCYCle" if channel == 1 else "PULSe:DCYC:CH2")):
                    expected = {"channel": channel, "waveform": waveform, "duty_percent": duty}

                    def run(channel=channel, suffix=suffix, duty=duty, waveform=waveform, command=command):
                        apply_wave(generator, channel, waveform, 1_000, 2.0)
                        generator.write(f"{command}{suffix if waveform == 'SQUare' else ''} {duty}")
                        time.sleep(0.25)
                        configure_scope(scope, channel, 1_000, 2.0)
                        observed = measure(scope, channel, "PDUTycycle", "FREQuency", "VPP")
                        observed["dg_duty"] = _number(generator.query_text(f"{command}{suffix if waveform == 'SQUare' else ''}?"))
                        return observed, {
                            "dg_duty": math.isclose(observed["dg_duty"], duty, abs_tol=0.2),
                            "scope_duty": math.isclose(observed["PDUTycycle"], duty / 100.0, abs_tol=0.06),
                            "frequency": math.isclose(observed["FREQuency"], 1_000, rel_tol=0.05),
                        }

                    recorder.case("dg-duty", f"ch{channel}-{waveform.lower()}-{duty:g}pct", expected, run)

            for symmetry in (20.0, 50.0, 80.0):
                expected = {"channel": channel, "symmetry_percent": symmetry}

                def run(channel=channel, suffix=suffix, symmetry=symmetry):
                    apply_wave(generator, channel, "RAMP", 1_000, 2.0)
                    generator.write(f"FUNCtion:RAMP:SYMMetry{suffix} {symmetry}")
                    time.sleep(0.35)
                    generator.write(f"FUNCtion:RAMP:SYMMetry{suffix} {symmetry}")
                    time.sleep(0.35)
                    configure_scope(scope, channel, 1_000, 2.0)
                    scope.write(":DISPlay:CLEar")
                    scope.write(":RUN")
                    time.sleep(0.6)
                    samples = capture(scope, channel)
                    diffs = [samples[index + 3] - samples[index] for index in range(len(samples) - 3)]
                    diffs = [value for value in diffs if abs(value) > 0.002]
                    rising = sum(value > 0 for value in diffs)
                    observed_ratio = 100.0 * rising / len(diffs)
                    observed = {
                        "dg_symmetry": _number(generator.query_text(f"FUNCtion:RAMP:SYMMetry{suffix}?")),
                        "sample_rising_percent": observed_ratio,
                        "sample_count": len(samples),
                    }
                    return observed, {
                        "dg_symmetry": math.isclose(observed["dg_symmetry"], symmetry, abs_tol=0.2),
                        "waveform_symmetry": math.isclose(observed_ratio, symmetry, abs_tol=12.0),
                    }

                recorder.case("dg-ramp-symmetry", f"ch{channel}-{symmetry:g}pct", expected, run)

            for amplitude in AMPLITUDES:
                expected = {"channel": channel, "noise_vpp": amplitude}

                def run(channel=channel, suffix=suffix, amplitude=amplitude):
                    generator.write(f"APPLy:NOISe{suffix} 1000,{amplitude},0")
                    time.sleep(0.35)
                    configure_scope(scope, channel, 1_000, amplitude)
                    observed = measure(scope, channel, "VPP", "VRMS", "VAVerage")
                    return observed, {
                        "nonzero_vpp": 0.15 * amplitude <= observed["VPP"] <= 2.0 * amplitude,
                        "nonzero_rms": 0.03 * amplitude <= observed["VRMS"] <= amplitude,
                        "near_zero_mean": abs(observed["VAVerage"]) <= max(0.15, amplitude * 0.2),
                    }

                recorder.case("dg-noise", f"ch{channel}-{amplitude:g}vpp", expected, run)


def _configure_long_capture(scope: Scope, time_scale: float, trigger_level: float = 0.0) -> None:
    _write_all(scope, [
        ":CHANnel1:DISPlay ON", ":CHANnel2:DISPlay ON",
        ":CHANnel1:COUPling DC", ":CHANnel2:COUPling DC",
        ":CHANnel1:PROBe 1", ":CHANnel2:PROBe 1",
        ":CHANnel1:SCALe 0.5", ":CHANnel2:SCALe 0.5",
        ":CHANnel1:OFFSet 0", ":CHANnel2:OFFSet 0",
        f":TIMebase:SCALe {_decimal(time_scale)}",
        ":TRIGger:MODE EDGE", ":TRIGger:EDGE:SOURce CHANnel1",
        ":TRIGger:EDGE:SLOPe POSitive", f":TRIGger:EDGE:LEVel {trigger_level}",
        ":TRIGger:EDGE:SWEep AUTO", ":WAVeform:POINts:MODE MAXimum",
        ":DISPlay:CLEar", ":RUN",
    ], extra_delay=0.015)
    time.sleep(0.6)


def dg_advanced(recorder: Recorder) -> None:
    with Generator(choose_generator(), command_delay_ms=100) as generator, Scope(choose_scope()) as scope:
        _write_all(generator, [
            "AM:STATe OFF", "FM:STATe OFF", "PM:STATe OFF", "FSK:STATe OFF",
            "SWEep:STATe OFF", "BURSt:STATe OFF", "COUPling OFF",
        ])

        # AM uses a 20 kHz carrier so several carrier cycles fit inside each
        # local-RMS window while the lower-frequency envelope remains visible.
        for mod_frequency in (100.0, 500.0, 1_000.0):
            for depth in (20.0, 50.0, 80.0):
                expected = {"carrier_hz": 20_000, "modulation_hz": mod_frequency, "depth_percent": depth}

                def run(mod_frequency=mod_frequency, depth=depth):
                    _dg_cli(generator, "output", "--channel", "1", "--waveform", "sine", "--frequency", "20kHz", "--amplitude", "2Vpp", "--enable")
                    _dg_cli(generator, "modulate", "am", "--source", "INT", "--internal-waveform", "SIN", "--internal-frequency", f"{mod_frequency:g}Hz", "--depth", f"{depth:g}", "--enable")
                    time_scale = 0.2 / mod_frequency
                    _configure_long_capture(scope, time_scale)
                    samples = capture(scope, 1, "MAXimum")
                    points_per_carrier = len(samples) / (12 * time_scale * 20_000)
                    envelope = _local_rms(samples, round(points_per_carrier * 3))
                    low = _percentile(envelope, 0.05)
                    high = _percentile(envelope, 0.95)
                    contrast = (high - low) / max(high + low, 1e-9)
                    observed = {
                        "state": generator.query_text("AM:STATe?"),
                        "source": generator.query_text("AM:SOURce?"),
                        "internal_frequency_hz": _number(generator.query_text("AM:INTernal:FREQuency?")),
                        "depth_percent": _number(generator.query_text("AM:DEPTh?")),
                        "envelope_contrast": contrast,
                        "sample_count": len(samples),
                    }
                    return observed, {
                        "state": observed["state"].strip().upper() == "ON",
                        "source": observed["source"].strip().upper().startswith("INT"),
                        "frequency": math.isclose(observed["internal_frequency_hz"], mod_frequency, rel_tol=0.01),
                        "depth": math.isclose(observed["depth_percent"], depth, abs_tol=0.5),
                        "physical_envelope": contrast >= max(0.04, depth / 500.0),
                    }

                recorder.case("dg-am-grid", f"{mod_frequency:g}hz-{depth:g}pct", expected, run)
        generator.write("AM:STATe OFF")

        for mode in ("fm", "pm"):
            for mod_frequency in (100.0, 500.0, 1_000.0):
                deviations = (500.0, 2_000.0, 4_000.0) if mode == "fm" else (30.0, 90.0, 180.0)
                for deviation in deviations:
                    expected = {"mode": mode.upper(), "carrier_hz": 10_000, "modulation_hz": mod_frequency, "deviation": deviation}

                    def run(mode=mode, mod_frequency=mod_frequency, deviation=deviation):
                        _dg_cli(generator, "output", "--channel", "1", "--waveform", "sine", "--frequency", "10kHz", "--amplitude", "2Vpp", "--enable")
                        _dg_cli(generator, "modulate", mode, "--source", "INT", "--internal-waveform", "SIN", "--internal-frequency", f"{mod_frequency:g}Hz", "--deviation", f"{deviation:g}", "--enable")
                        time_scale = 0.2 / mod_frequency
                        _configure_long_capture(scope, time_scale)
                        samples = capture(scope, 1, "MAXimum")
                        sample_rate = _number(scope.query_text(":ACQuire:SAMPlingrate? CHANnel1"))
                        frequencies = _crossing_frequencies(samples, sample_rate)
                        p05 = _percentile(frequencies, 0.05)
                        p95 = _percentile(frequencies, 0.95)
                        carrier_amplitude = _tone_amplitude(samples, 10_000, sample_rate)
                        sideband_amplitude = statistics.mean((
                            _tone_amplitude(samples, 10_000 - mod_frequency, sample_rate),
                            _tone_amplitude(samples, 10_000 + mod_frequency, sample_rate),
                        ))
                        sideband_ratio = sideband_amplitude / max(carrier_amplitude, 1e-9)
                        prefix = mode.upper()
                        observed = {
                            "state": generator.query_text(f"{prefix}:STATe?"),
                            "internal_frequency_hz": _number(generator.query_text(f"{prefix}:INTernal:FREQuency?")),
                            "deviation": _number(generator.query_text(f"{prefix}:DEViation?")),
                            "instantaneous_frequency_p05_hz": p05,
                            "instantaneous_frequency_p95_hz": p95,
                            "frequency_span_hz": p95 - p05,
                            "sideband_carrier_ratio": sideband_ratio,
                        }
                        minimum_span = deviation * 0.5 if mode == "fm" else max(30.0, deviation * mod_frequency / 400.0)
                        return observed, {
                            "state": observed["state"].strip().upper() == "ON",
                            "modulation_frequency": math.isclose(observed["internal_frequency_hz"], mod_frequency, rel_tol=0.01),
                            "deviation": math.isclose(observed["deviation"], deviation, rel_tol=0.01, abs_tol=0.5),
                            "physical_frequency_variation": observed["frequency_span_hz"] >= minimum_span or (mode == "pm" and sideband_ratio >= 0.03),
                        }

                    recorder.case(f"dg-{mode}-grid", f"{mod_frequency:g}hz-{deviation:g}", expected, run)
            generator.write(f"{mode.upper()}:STATe OFF")

        for rate in (100.0, 500.0, 1_000.0):
            for hop in (5_000.0, 15_000.0, 20_000.0):
                expected = {"carrier_hz": 10_000, "hop_hz": hop, "rate_hz": rate}

                def run(rate=rate, hop=hop):
                    _dg_cli(generator, "output", "--channel", "1", "--waveform", "sine", "--frequency", "10kHz", "--amplitude", "2Vpp", "--enable")
                    _dg_cli(generator, "modulate", "fsk", "--source", "INT", "--hop-frequency", f"{hop:g}Hz", "--rate", f"{rate:g}Hz", "--enable")
                    time_scale = 0.2 / rate
                    _configure_long_capture(scope, time_scale)
                    samples = capture(scope, 1, "MAXimum")
                    sample_rate = _number(scope.query_text(":ACQuire:SAMPlingrate? CHANnel1"))
                    frequencies = _crossing_frequencies(samples, sample_rate)
                    p10 = _percentile(frequencies, 0.10)
                    p90 = _percentile(frequencies, 0.90)
                    observed = {
                        "state": generator.query_text("FSK:STATe?"),
                        "hop_hz": _number(generator.query_text("FSK:FREQuency?")),
                        "rate_hz": _number(generator.query_text("FSK:INTernal:RATE?")),
                        "frequency_p10_hz": p10,
                        "frequency_p90_hz": p90,
                    }
                    expected_low, expected_high = sorted((10_000.0, hop))
                    return observed, {
                        "state": observed["state"].strip().upper() == "ON",
                        "hop": math.isclose(observed["hop_hz"], hop, rel_tol=0.01),
                        "rate": math.isclose(observed["rate_hz"], rate, rel_tol=0.01),
                        "physical_low": math.isclose(p10, expected_low, rel_tol=0.18),
                        "physical_high": math.isclose(p90, expected_high, rel_tol=0.18),
                    }

                recorder.case("dg-fsk-grid", f"{rate:g}hz-{hop:g}hz", expected, run)
        generator.write("FSK:STATe OFF")

        for spacing in ("LIN", "LOG"):
            for start, stop in ((200.0, 2_000.0), (1_000.0, 10_000.0), (5_000.0, 20_000.0)):
                expected = {"spacing": spacing, "start_hz": start, "stop_hz": stop, "time_s": 0.1}

                def run(spacing=spacing, start=start, stop=stop):
                    _dg_cli(generator, "output", "--channel", "1", "--waveform", "sine", "--frequency", f"{start:g}Hz", "--amplitude", "2Vpp", "--enable")
                    _dg_cli(generator, "sweep-config", "--start", f"{start:g}Hz", "--stop", f"{stop:g}Hz", "--time", "0.1", "--spacing", spacing, "--trigger-source", "IMM", "--enable")
                    time_scale = 0.01
                    _configure_long_capture(scope, time_scale)
                    samples = capture(scope, 1, "MAXimum")
                    sample_rate = _number(scope.query_text(":ACQuire:SAMPlingrate? CHANnel1"))
                    frequencies = _crossing_frequencies(samples, sample_rate)
                    p02 = _percentile(frequencies, 0.02)
                    p98 = _percentile(frequencies, 0.98)
                    observed = {
                        "state": generator.query_text("SWEep:STATe?"),
                        "spacing": generator.query_text("SWEep:SPACing?"),
                        "start_hz": _number(generator.query_text("FREQuency:STARt?")),
                        "stop_hz": _number(generator.query_text("FREQuency:STOP?")),
                        "frequency_p02_hz": p02,
                        "frequency_p98_hz": p98,
                    }
                    return observed, {
                        "state": observed["state"].strip().upper() == "ON",
                        "spacing": observed["spacing"].strip().upper().startswith(spacing),
                        "start": math.isclose(observed["start_hz"], start, rel_tol=0.01),
                        "stop": math.isclose(observed["stop_hz"], stop, rel_tol=0.01),
                        "physical_variation": p98 - p02 >= 0.3 * (stop - start),
                    }

                recorder.case("dg-sweep-grid", f"{spacing.lower()}-{start:g}-{stop:g}", expected, run)
        generator.write("SWEep:STATe OFF")

        for cycles in (1, 3, 5, 10):
            for period in (0.01, 0.02):
                expected = {"cycles": cycles, "period_s": period, "carrier_hz": 2_000}

                def run(cycles=cycles, period=period):
                    _dg_cli(generator, "output", "--channel", "1", "--waveform", "sine", "--frequency", "2kHz", "--amplitude", "2Vpp", "--enable")
                    _dg_cli(generator, "burst-config", "--mode", "TRIG", "--cycles", str(cycles), "--period", str(period), "--phase", "0", "--trigger-source", "IMM", "--enable")
                    time_scale = period / 4
                    _configure_long_capture(scope, time_scale)
                    samples = capture(scope, 1, "MAXimum")
                    threshold = max(abs(value) for value in samples) * 0.3
                    active = [abs(value) > threshold for value in samples]
                    groups: list[int] = []
                    count = 0
                    max_gap = max(2, round(len(samples) * (0.0002 / (12 * time_scale))))
                    gap = 0
                    for is_active in active:
                        if is_active:
                            if gap > max_gap and count:
                                groups.append(count)
                                count = 0
                            count += 1
                            gap = 0
                        elif count:
                            gap += 1
                    if count:
                        groups.append(count)
                    sample_rate = _number(scope.query_text(":ACQuire:SAMPlingrate? CHANnel1"))
                    crossings = _crossing_frequencies(samples, sample_rate)
                    observed = {
                        "state": generator.query_text("BURSt:STATe?"),
                        "cycles": _number(generator.query_text("BURSt:NCYCles?")),
                        "period_s": _number(generator.query_text("BURSt:INTernal:PERiod?")),
                        "active_groups": len(groups),
                        "frequency_median_hz": statistics.median(crossings) if crossings else 0,
                    }
                    return observed, {
                        "state": observed["state"].strip().upper() == "ON",
                        "cycles": math.isclose(observed["cycles"], cycles, abs_tol=0.1),
                        "period": math.isclose(observed["period_s"], period, rel_tol=0.02),
                        "physical_gaps": observed["active_groups"] >= 2,
                    }

                recorder.case("dg-burst-grid", f"{cycles}cycles-{period:g}s", expected, run)
        generator.write("BURSt:STATe OFF")

        _dg_cli(generator, "output", "--channel", "1", "--waveform", "sine", "--frequency", "1kHz", "--amplitude", "2Vpp", "--phase", "0", "--enable")
        for phase in (0.0, 45.0, 90.0, 135.0, 180.0, -90.0):
            expected = {"channel2_phase_degrees": phase, "frequency_hz": 1_000}

            def run(phase=phase):
                _dg_cli(generator, "output", "--channel", "2", "--waveform", "sine", "--frequency", "1kHz", "--amplitude", "2Vpp", "--phase", f"{phase:g}", "--enable")
                time_scale = 0.0002
                _configure_long_capture(scope, time_scale)
                samples1, samples2 = capture_pair(scope)
                sample_rate = _number(scope.query_text(":ACQuire:SAMPlingrate? CHANnel1"))
                phase1 = _fundamental_phase(samples1, 1_000, sample_rate)
                phase2 = _fundamental_phase(samples2, 1_000, sample_rate)
                measured = (phase2 - phase1 + 180) % 360 - 180
                target = (phase + 180) % 360 - 180
                error = min(abs(measured - target), abs(measured - target + 360), abs(measured - target - 360))
                observed = {
                    "dg_phase_ch2": _number(generator.query_text("PHASe:CH2?")),
                    "measured_phase_degrees": measured,
                    "absolute_error_degrees": error,
                    "points_ch1": len(samples1), "points_ch2": len(samples2),
                }
                return observed, {
                    "register": math.isclose(((observed["dg_phase_ch2"] - target + 180) % 360) - 180, 0, abs_tol=0.5),
                    "physical_phase": error <= 15.0,
                    "synchronized_depth": len(samples1) >= 8_000 and len(samples2) >= 8_000,
                }

            recorder.case("dg-phase-grid", f"{phase:+g}deg", expected, run)

        # Channel-local output controls and copy/coupling paths.
        for channel in (1, 2):
            suffix = _dg_suffix(channel)
            for polarity in ("NORMal", "INVerted"):
                expected = {"channel": channel, "polarity": polarity}

                def run(channel=channel, suffix=suffix, polarity=polarity):
                    generator.write(f"OUTPut:POLarity{suffix} {polarity}")
                    observed = {"polarity": generator.query_text(f"OUTPut:POLarity{suffix}?")}
                    return observed, {"readback": observed["polarity"].upper().startswith(polarity[:3].upper())}

                recorder.case("dg-output-controls", f"ch{channel}-{polarity.lower()}", expected, run)
            generator.write(f"OUTPut:POLarity{suffix} NORMal")
            for load in (50.0, 100.0, 1_000.0, math.inf):
                value = "INFinity" if math.isinf(load) else f"{load:g}"
                expected = {"channel": channel, "load": value}

                def run(suffix=suffix, load=load, value=value):
                    generator.write(f"OUTPut:LOAD{suffix} {value}")
                    response = generator.query_text(f"OUTPut:LOAD{suffix}?").strip()
                    readback = math.inf if response.upper().startswith("INF") else _number(response)
                    return {"load_ohms": response}, {"readback": (math.isinf(readback) if math.isinf(load) else math.isclose(readback, load, rel_tol=0.01))}

                recorder.case("dg-output-controls", f"ch{channel}-load-{value.lower()}", expected, run)
            generator.write(f"OUTPut:LOAD{suffix} INFinity")

        generator.write("COUPling:BASEdchannel:CH1")
        generator.write("COUPling:FREQDEViation 1234")
        generator.write("COUPling:PHASEDEViation 45")
        generator.write("COUPling ON")
        time.sleep(0.5)
        coupling_enabled = generator.query_text("COUPling?")
        generator.write("COUPling OFF")

        def run_coupling():
            observed = {
                "base": generator.query_text("COUPling:BASEdchannel?"),
                "frequency_deviation": _number(generator.query_text("COUPling:FREQDEViation?")),
                "phase_deviation": _number(generator.query_text("COUPling:PHASEDEViation?")),
                "enabled": coupling_enabled,
            }
            return observed, {
                "base": observed["base"].upper().endswith("CH1"),
                "frequency": math.isclose(observed["frequency_deviation"], 1234, rel_tol=0.01),
                "phase": math.isclose(observed["phase_deviation"], 45, abs_tol=0.5),
                "enabled": observed["enabled"].strip().upper() == "ON",
            }

        recorder.case("dg-coupling", "registers", {"base": "CH1", "frequency_deviation": 1234, "phase_deviation": 45}, run_coupling)

        generator.write("APPLy:RAMP 1234,1.5,0.2")
        generator.write("FUNCtion:RAMP:SYMMetry 30")
        generator.write("PHASe 30")
        generator.write("COUPling:CHANNCopy 1>2")
        time.sleep(0.5)
        recorder.case("dg-channel-copy", "ch1-to-ch2", {"function": "RAMP", "frequency": 1234, "amplitude": 1.5, "offset": 0.2}, lambda: (
            {
                "function": generator.query_text("FUNCtion:CH2?"),
                "frequency": _number(generator.query_text("FREQuency:CH2?")),
                "amplitude": _number(generator.query_text("VOLTage:CH2?")),
                "offset": _number(generator.query_text("VOLTage:OFFSet:CH2?")),
                "phase": _number(generator.query_text("PHASe:CH2?")),
            },
            {
                "function": "RAMP" in generator.query_text("FUNCtion:CH2?").upper(),
                "frequency": math.isclose(_number(generator.query_text("FREQuency:CH2?")), 1234, rel_tol=0.01),
                "amplitude": math.isclose(_number(generator.query_text("VOLTage:CH2?")), 1.5, rel_tol=0.01),
                "offset": math.isclose(_number(generator.query_text("VOLTage:OFFSet:CH2?")), 0.2, abs_tol=0.01),
            }
        ))

    # ARB lifecycle is deliberately performed through the installed CLI entry
    # point, including all three output formats and both normalized/DAC inputs.
    with tempfile.TemporaryDirectory(prefix="dg1022-acceptance-") as directory:
        temp = Path(directory)
        arb_cases = ((4, False), (17, True), (257, False), (4_096, True))
        for index, (points, dac) in enumerate(arb_cases):
            name = f"QA{index}_{points}"
            source = temp / f"{name}.txt"
            if dac:
                source.write_text("\n".join(str(round(8191.5 + 8191.5 * math.sin(2 * math.pi * item / points))) for item in range(points)) + "\n")
            else:
                source.write_text("\n".join(f"{math.sin(2 * math.pi * item / points):.9f}" for item in range(points)) + "\n")
            expected = {"input_points": points, "dac": dac, "name": name}

            def run(points=points, dac=dac, name=name, source=source):
                args = ["arb", "upload", str(source), "--name", name, "--select", "--enable"]
                if dac:
                    args.append("--dac")
                _cli("dg1022", *args)
                outputs: dict[str, Any] = {}
                for format_name in ("bin", "csv", "json"):
                    path = temp / f"{name}.{format_name}"
                    _cli("dg1022", "arb", "download", name, "--format", format_name, "--output", str(path))
                    outputs[f"{format_name}_bytes"] = path.stat().st_size
                    if format_name == "json":
                        outputs["device_points"] = json.loads(path.read_text())["points"]
                catalog = _cli("dg1022", "arb", "list")
                _cli("dg1022", "arb", "delete", name)
                return {**outputs, "catalog_contained_name": name in catalog}, {
                    "catalog": name in catalog,
                    "expanded_points": outputs["device_points"] >= points,
                    "bin": outputs["bin_bytes"] == outputs["device_points"] * 2,
                    "csv": outputs["csv_bytes"] > outputs["device_points"] * 4,
                    "json": outputs["json_bytes"] > outputs["device_points"] * 2,
                }

            recorder.case("dg-arb-lifecycle", name, expected, run)


def ds_core(recorder: Recorder) -> None:
    with Generator(choose_generator(), command_delay_ms=100) as generator, Scope(choose_scope()) as scope:
        _write_all(generator, [
            "AM:STATe OFF", "FM:STATe OFF", "PM:STATe OFF", "FSK:STATe OFF",
            "SWEep:STATe OFF", "BURSt:STATe OFF", "COUPling OFF",
            "APPLy:SQUare 1000,2,0", "FUNCtion:SQUare:DCYCle 40", "OUTPut ON",
            "APPLy:PULSe:CH2 2000,2,0", "PULSe:DCYC:CH2 60", "OUTPut:CH2 ON",
        ])
        configure_scope(scope, 1, 1_000, 2.0)

        acquisition_options = (
            ("acquire.type", ("NORMal", "AVERage", "PEAKdetect")),
            ("acquire.mode", ("REAL_TIME", "EQUAL_TIME", "ROLL")),
            ("acquire.averages", ("2", "4", "8", "16", "32", "64", "128", "256")),
            ("acquire.memory-depth", ("NORMal", "LONG")),
        )
        for command_name, values in acquisition_options:
            for value in values:
                expected = {"command": command_name, "value": value}

                def run(command_name=command_name, value=value):
                    if command_name == "acquire.mode":
                        scope.write(":ACQuire:TYPE NORMal")
                        scope.write(":TIMebase:FORMat YT")
                    if command_name == "acquire.mode" and value == "ROLL":
                        scope.write(":TIMebase:SCALe 1")
                    output = _scope_cli(scope, "set", command_name, value)
                    readback = _scope_cli(scope, "get", command_name)
                    if command_name == "acquire.mode" and value == "ROLL":
                        return {"set_output": output, "readback": readback, "device_limitation": "documented ROLL value ignored by DS1152E firmware"}, {
                            "firmware_limitation_reproduced": not readback.upper().startswith("ROLL")
                        }
                    return {"set_output": output, "readback": readback}, {
                        "readback": readback.upper().replace("_", "").startswith(value.upper().replace("_", "")[:4])
                    }

                recorder.case("ds-acquisition-registers", f"{command_name}-{value}", expected, run)

        _write_all(scope, [
            ":ACQuire:TYPE NORMal", ":ACQuire:MODE REAL_TIME", ":ACQuire:MEMDepth LONG",
            ":TIMebase:SCALe 0.0002", ":RUN",
        ])
        time.sleep(0.5)
        for channel in (1, 2):
            for mode, minimum, maximum in (("NORMal", 500, 700), ("MAXimum", 8_000, 1_100_000), ("RAW", 8_000, 1_100_000)):
                expected = {"channel": channel, "mode": mode, "point_range": [minimum, maximum]}

                def run(channel=channel, mode=mode, minimum=minimum, maximum=maximum):
                    samples = capture(scope, channel, mode)
                    return {
                        "point_count": len(samples),
                        "minimum_v": min(samples),
                        "maximum_v": max(samples),
                        "points_mode_after": scope.query_text(":WAVeform:POINts:MODE?"),
                    }, {
                        "point_count": minimum <= len(samples) <= maximum,
                        "physical_signal": max(samples) - min(samples) >= 1.5,
                        "mode_restored": scope.query_text(":WAVeform:POINts:MODE?").upper().startswith("MAX"),
                    }

                recorder.case("ds-waveform-depth", f"ch{channel}-{mode.lower()}", expected, run)

        for channel in (1, 2):
            source = f"CHANnel{channel}"
            for coupling in ("DC", "AC", "GND"):
                expected = {"channel": channel, "coupling": coupling}

                def run(channel=channel, source=source, coupling=coupling):
                    _scope_cli(scope, "set", "channel.coupling", coupling, "--channel", str(channel))
                    time.sleep(0.5)
                    samples = capture(scope, channel)
                    readback = _scope_cli(scope, "get", "channel.coupling", "--channel", str(channel))
                    span = max(samples) - min(samples)
                    return {"readback": readback, "sample_span_v": span, "mean_v": statistics.mean(samples)}, {
                        "readback": readback.upper().startswith(coupling),
                        "physical": span < 0.25 if coupling == "GND" else span > 1.5,
                    }

                recorder.case("ds-channel-coupling", f"ch{channel}-{coupling.lower()}", expected, run)
            scope.write(f":CHANnel{channel}:COUPling DC")

            for setting in ("OFF", "ON"):
                for name in ("channel.invert", "channel.bandwidth-limit", "channel.filter", "channel.vernier"):
                    expected = {"channel": channel, "command": name, "value": setting}

                    def run(channel=channel, setting=setting, name=name):
                        _scope_cli(scope, "set", name, setting, "--channel", str(channel))
                        readback = _scope_cli(scope, "get", name, "--channel", str(channel))
                        expected_readback = ("FINE" if setting == "ON" else "COARSE") if name == "channel.vernier" else setting
                        return {"readback": readback}, {"readback": readback.strip().upper() == expected_readback}

                    recorder.case("ds-channel-switches", f"ch{channel}-{name}-{setting.lower()}", expected, run)
            _write_all(scope, [
                f":CHANnel{channel}:INVert OFF", f":CHANnel{channel}:BWLimit OFF",
                f":CHANnel{channel}:FILTer OFF", f":CHANnel{channel}:VERNier OFF",
            ])

            for probe in (1, 5, 10, 100, 1_000):
                expected = {"channel": channel, "probe": probe}

                def run(channel=channel, probe=probe):
                    _scope_cli(scope, "set", "channel.probe", str(probe), "--channel", str(channel))
                    readback = _number(_scope_cli(scope, "get", "channel.probe", "--channel", str(channel)))
                    return {"readback": readback}, {"readback": math.isclose(readback, probe, rel_tol=0.001)}

                recorder.case("ds-probe-grid", f"ch{channel}-{probe}x", expected, run)
            scope.write(f":CHANnel{channel}:PROBe 1")

            for scale in (0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0):
                expected = {"channel": channel, "scale_v_div": scale}

                def run(channel=channel, scale=scale):
                    value = _decimal(scale)
                    _scope_cli(scope, "set", "channel.scale", value, "--channel", str(channel))
                    readback = _number(_scope_cli(scope, "get", "channel.scale", "--channel", str(channel)))
                    return {"readback": readback}, {"readback": math.isclose(readback, scale, rel_tol=0.001)}

                recorder.case("ds-scale-grid", f"ch{channel}-{scale:g}vdiv", expected, run)
            scope.write(f":CHANnel{channel}:SCALe 0.5")

            for offset in (-1.0, -0.5, 0.0, 0.5, 1.0):
                expected = {"channel": channel, "offset_v": offset}

                def run(channel=channel, offset=offset):
                    _scope_cli(scope, "set", "channel.offset", _decimal(offset), "--channel", str(channel))
                    readback = _number(_scope_cli(scope, "get", "channel.offset", "--channel", str(channel)))
                    return {"readback": readback}, {"readback": math.isclose(readback, offset, abs_tol=0.005)}

                recorder.case("ds-offset-grid", f"ch{channel}-{offset:+g}v", expected, run)
            scope.write(f":CHANnel{channel}:OFFSet 0")

        configure_scope(scope, 1, 1_000, 2.0)
        all_measurements = json.loads(_scope_cli(scope, "measure", "all", "--channel", "1", "--json"))["measurements"]
        all_measurements_ch2 = json.loads(_scope_cli(scope, "measure", "all", "--channel", "2", "--json"))["measurements"]
        measurement_expectations = {
            "vpp": lambda value, channel: 1.5 <= value <= 2.5,
            "vmax": lambda value, channel: 0.7 <= value <= 1.3,
            "vmin": lambda value, channel: -1.3 <= value <= -0.7,
            "vamplitude": lambda value, channel: 1.5 <= value <= 2.5,
            "vtop": lambda value, channel: 0.7 <= value <= 1.3,
            "vbase": lambda value, channel: -1.3 <= value <= -0.7,
            "vaverage": lambda value, channel: abs(value) <= 0.3,
            "vrms": lambda value, channel: 0.7 <= value <= 1.2,
            "frequency": lambda value, channel: math.isclose(value, 1_000 if channel == 1 else 2_000, rel_tol=0.08),
            "period": lambda value, channel: math.isclose(value, 0.001 if channel == 1 else 0.0005, rel_tol=0.08),
            "positive-duty": lambda value, channel: abs(value - (0.4 if channel == 1 else 0.6)) <= 0.08,
            "negative-duty": lambda value, channel: abs(value - (0.6 if channel == 1 else 0.4)) <= 0.08,
        }
        for channel, measurements in ((1, all_measurements), (2, all_measurements_ch2)):
            for metric, value in measurements.items():
                expected = {"channel": channel, "metric": metric, "response": "finite or documented unavailable"}

                def run(channel=channel, metric=metric, value=value):
                    finite = isinstance(value, (int, float)) and math.isfinite(value)
                    documented_unavailable = value == "unavailable"
                    bounded_numeric = isinstance(value, str) and re.fullmatch(r"[<>][+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value) is not None
                    physical = True
                    if metric in measurement_expectations:
                        physical = finite and measurement_expectations[metric](float(value), channel)
                    return {"value": value}, {
                        "typed_response": finite or documented_unavailable or bounded_numeric,
                        "physical_when_applicable": physical,
                    }

                recorder.case("ds-automatic-measurements", f"ch{channel}-{metric}", expected, run)

        with tempfile.TemporaryDirectory(prefix="ds1152e-waveform-") as directory:
            temp = Path(directory)
            combinations = [
                (channel, mode, format_name)
                for channel in (1, 2)
                for mode, format_name in (("normal", "csv"), ("normal", "json"), ("normal", "bin"),
                                          ("maximum", "csv"), ("maximum", "json"), ("maximum", "bin"),
                                          ("raw", "csv"), ("raw", "json"), ("raw", "bin"))
            ]
            for channel, mode, format_name in combinations:
                expected = {"channel": channel, "mode": mode, "format": format_name}

                def run(channel=channel, mode=mode, format_name=format_name):
                    path = temp / f"ch{channel}-{mode}.{format_name}"
                    _scope_cli(scope, "waveform", "--source", f"ch{channel}", "--points-mode", mode,
                               "--format", format_name, "--output", str(path), "--stop")
                    size = path.stat().st_size
                    points = size if format_name == "bin" else None
                    calibrated = True
                    if format_name == "json":
                        payload = json.loads(path.read_text())
                        points = payload["points"]
                        calibrated = all(item["volts"] is not None for item in payload["samples"][:10])
                    elif format_name == "csv":
                        with path.open() as stream:
                            header = stream.readline().strip()
                            points = sum(1 for _ in stream)
                        calibrated = header == "index,time_seconds,raw,volts"
                    minimum = 500 if mode == "normal" else 8_000
                    return {"bytes": size, "points": points, "calibrated": calibrated}, {
                        "nonempty": size > 100,
                        "point_count": points is not None and points >= minimum,
                        "calibrated": calibrated,
                    }

                recorder.case("ds-cli-waveform-export", f"ch{channel}-{mode}-{format_name}", expected, run)


def ds_triggers_math(recorder: Recorder) -> None:
    with Generator(choose_generator(), command_delay_ms=100) as generator, Scope(choose_scope()) as scope:
        _write_all(generator, [
            "AM:STATe OFF", "FM:STATe OFF", "PM:STATe OFF", "FSK:STATe OFF",
            "SWEep:STATe OFF", "BURSt:STATe OFF", "COUPling OFF",
            "APPLy:SQUare 1000,2,0", "FUNCtion:SQUare:DCYCle 40", "OUTPut ON",
            "APPLy:PULSe:CH2 2000,2,0", "PULSe:DCYC:CH2 60", "OUTPut:CH2 ON",
        ])
        configure_scope(scope, 1, 1_000, 2.0)

        for source in ("CHANnel1", "CHANnel2"):
            channel = 1 if source.endswith("1") else 2
            frequency = 1_000 if channel == 1 else 2_000
            for slope in ("POSitive", "NEGative"):
                for level in (-0.5, 0.0, 0.5):
                    expected = {"source": source, "slope": slope, "level_v": level}

                    def run(source=source, channel=channel, frequency=frequency, slope=slope, level=level):
                        _scope_cli(scope, "set", "trigger.mode", "EDGE")
                        _scope_cli(scope, "set", "trigger.source", source, "--mode", "EDGE")
                        _scope_cli(scope, "set", "trigger.edge.slope", slope)
                        _scope_cli(scope, "set", "trigger.level", _decimal(level), "--mode", "EDGE")
                        _scope_cli(scope, "set", "trigger.sweep", "NORMal", "--mode", "EDGE")
                        scope.write(":RUN")
                        time.sleep(0.3)
                        measured_vpp = _number(scope.query_text(f":MEASure:VPP? CHANnel{channel}"))
                        observed = {
                            "mode": _scope_cli(scope, "get", "trigger.mode"),
                            "source": _scope_cli(scope, "get", "trigger.source", "--mode", "EDGE"),
                            "slope": _scope_cli(scope, "get", "trigger.edge.slope"),
                            "level_v": _number(_scope_cli(scope, "get", "trigger.level", "--mode", "EDGE")),
                            "status": _scope_cli(scope, "get", "trigger.status"),
                            "measured_vpp": measured_vpp,
                        }
                        return observed, {
                            "mode": observed["mode"].upper().startswith("EDGE"),
                            "source": observed["source"].upper().endswith(str(channel)),
                            "slope": observed["slope"].upper().startswith(slope[:3].upper()),
                            "level": math.isclose(observed["level_v"], level, abs_tol=0.02),
                            "physical_signal": 1.5 <= measured_vpp <= 2.5,
                            "active_status": observed["status"].strip().upper() not in {"STOP", "STOPPED"},
                        }

                    recorder.case("ds-trigger-edge-grid", f"ch{channel}-{slope[:3].lower()}-{level:+g}v", expected, run)

        for mode in ("+GREaterthan", "+LESSthan", "-GREaterthan", "-LESSthan"):
            for width in (0.0001, 0.0005, 0.001):
                expected = {"mode": mode, "width_s": width, "source": "CHANnel1"}

                def run(mode=mode, width=width):
                    _scope_cli(scope, "set", "trigger.mode", "PULSe")
                    _scope_cli(scope, "set", "trigger.source", "CHANnel1", "--mode", "PULSE")
                    _scope_cli(scope, "set", "trigger.level", "0", "--mode", "PULSE")
                    _scope_cli(scope, "set", "trigger.pulse.mode", mode)
                    _scope_cli(scope, "set", "trigger.pulse.width", _decimal(width))
                    _scope_cli(scope, "set", "trigger.pulse.sensitivity", "0.5")
                    _scope_cli(scope, "set", "trigger.sweep", "AUTO", "--mode", "PULSE")
                    observed = {
                        "mode": _scope_cli(scope, "get", "trigger.pulse.mode"),
                        "width_s": _number(_scope_cli(scope, "get", "trigger.pulse.width")),
                        "sensitivity_div": _number(_scope_cli(scope, "get", "trigger.pulse.sensitivity")),
                        "source": _scope_cli(scope, "get", "trigger.source", "--mode", "PULSE"),
                    }
                    normalized = observed["mode"].upper().replace(" ", "")
                    return observed, {
                        "mode": ("GREATER" if "GRE" in mode.upper() else "LESS") in normalized,
                        "polarity": normalized.startswith(mode[0]),
                        "width": math.isclose(observed["width_s"], width, rel_tol=0.02),
                        "sensitivity": math.isclose(observed["sensitivity_div"], 0.5, abs_tol=0.01),
                    }

                recorder.case("ds-trigger-pulse-grid", f"{mode}-{width:g}s", expected, run)

        for mode in ("+GREaterthan", "+LESSthan", "-GREaterthan", "-LESSthan"):
            valid_windows = ("PA", "PB") if mode.startswith("+") else ("NA", "NB")
            for window in valid_windows:
                for threshold_time in (0.00005, 0.0002):
                    expected = {"mode": mode, "window": window, "time_s": threshold_time}

                    def run(mode=mode, window=window, threshold_time=threshold_time):
                        _scope_cli(scope, "set", "trigger.mode", "SLOPe")
                        _scope_cli(scope, "set", "trigger.source", "CHANnel1", "--mode", "SLOPE")
                        _scope_cli(scope, "set", "trigger.slope.mode", mode)
                        _scope_cli(scope, "set", "trigger.slope.window", window)
                        level_a, level_b = (0.5, -0.5) if mode.startswith("+") else (-0.5, 0.5)
                        _scope_cli(scope, "set", "trigger.slope.level-a", str(level_a))
                        _scope_cli(scope, "set", "trigger.slope.level-b", str(level_b))
                        _scope_cli(scope, "set", "trigger.slope.time", _decimal(threshold_time))
                        _scope_cli(scope, "set", "trigger.slope.sensitivity", "0.5")
                        observed = {
                            "mode": _scope_cli(scope, "get", "trigger.slope.mode"),
                            "window": _scope_cli(scope, "get", "trigger.slope.window"),
                            "level_a": _number(_scope_cli(scope, "get", "trigger.slope.level-a")),
                            "level_b": _number(_scope_cli(scope, "get", "trigger.slope.level-b")),
                            "time_s": _number(_scope_cli(scope, "get", "trigger.slope.time")),
                        }
                        return observed, {
                            "mode_relation": ("GREATER" if "GRE" in mode.upper() else "LESS") in observed["mode"].upper().replace(" ", ""),
                            "window": observed["window"].strip().upper() == {"PA": "P_WIN_A", "PB": "P_WIN_B", "NA": "N_WIN_A", "NB": "N_WIN_B"}[window],
                            "levels": math.isclose(observed["level_a"], level_a, abs_tol=0.02) and math.isclose(observed["level_b"], level_b, abs_tol=0.02),
                            "time": math.isclose(observed["time_s"], threshold_time, rel_tol=0.03),
                        }

                    recorder.case("ds-trigger-slope-grid", f"{mode}-{window}-{threshold_time:g}s", expected, run)

        for value, mask in ((0, 0), (1, 1), (0x55AA, 0xFFFF), (0xAAAA, 0xF0F0)):
            expected = {"value": value, "mask": mask}

            def run(value=value, mask=mask):
                _scope_cli(scope, "set", "trigger.mode", "PATTern")
                _scope_cli(scope, "set", "trigger.pattern.pattern", f"{value},{mask}")
                readback = _scope_cli(scope, "get", "trigger.pattern.pattern")
                numbers = [int(part.strip()) for part in readback.split(",")[:2]]
                return {"readback": readback, "value": numbers[0], "mask": numbers[1]}, {
                    "value": numbers[0] == (value & mask),
                    "mask": numbers[1] == mask,
                }

            recorder.case("ds-trigger-pattern-grid", f"{value}-{mask}", expected, run)

        for value, mask in ((0, 0), (1, 1), (0x55AA, 0xFFFF)):
            for qualifier in ("GREaterthan", "LESSthan"):
                for duration in (0.000001, 0.001):
                    expected = {"value": value, "mask": mask, "qualifier": qualifier, "time_s": duration}

                    def run(value=value, mask=mask, qualifier=qualifier, duration=duration):
                        _scope_cli(scope, "set", "trigger.mode", "DURation")
                        _scope_cli(scope, "set", "trigger.duration.pattern", f"{value},{mask}")
                        _scope_cli(scope, "set", "trigger.duration.qualifier", qualifier)
                        _scope_cli(scope, "set", "trigger.duration.time", _decimal(duration))
                        pattern = _scope_cli(scope, "get", "trigger.duration.pattern")
                        numbers = [int(part.strip()) for part in pattern.split(",")[:2]]
                        observed = {
                            "pattern": pattern,
                            "qualifier": _scope_cli(scope, "get", "trigger.duration.qualifier"),
                            "time_s": _number(_scope_cli(scope, "get", "trigger.duration.time")),
                        }
                        return observed, {
                            "pattern": numbers == [value, mask],
                            "qualifier": qualifier[:3].upper() in observed["qualifier"].upper(),
                            "time": math.isclose(observed["time_s"], duration, rel_tol=0.03),
                        }

                    recorder.case("ds-trigger-duration-grid", f"{value}-{mask}-{qualifier}-{duration:g}s", expected, run)

        for standard in ("NTSC", "PALSecam"):
            for video_mode in ("ODDfield", "EVENfield", "LINE", "ALLLines"):
                for polarity in ("POSitive", "NEGative"):
                    expected = {"standard": standard, "mode": video_mode, "polarity": polarity}

                    def run(standard=standard, video_mode=video_mode, polarity=polarity):
                        _scope_cli(scope, "set", "trigger.mode", "VIDEO")
                        _scope_cli(scope, "set", "trigger.source", "CHANnel1", "--mode", "VIDEO")
                        _scope_cli(scope, "set", "trigger.video.standard", standard)
                        _scope_cli(scope, "set", "trigger.video.mode", video_mode)
                        _scope_cli(scope, "set", "trigger.video.polarity", polarity)
                        if video_mode == "LINE":
                            _scope_cli(scope, "set", "trigger.video.line", "10")
                        observed = {
                            "standard": _scope_cli(scope, "get", "trigger.video.standard"),
                            "mode": _scope_cli(scope, "get", "trigger.video.mode"),
                            "polarity": _scope_cli(scope, "get", "trigger.video.polarity"),
                            "line": _number(_scope_cli(scope, "get", "trigger.video.line")),
                        }
                        return observed, {
                            "standard": observed["standard"].upper().startswith(standard[:3].upper()),
                            "mode": video_mode[:3].upper() in observed["mode"].upper().replace(" ", ""),
                            "polarity": observed["polarity"].upper().startswith(polarity[:3].upper()),
                            "line": video_mode != "LINE" or math.isclose(observed["line"], 10, abs_tol=1),
                        }

                    recorder.case("ds-trigger-video-grid", f"{standard}-{video_mode}-{polarity}", expected, run)

        for source in ("CHANnel1", "CHANnel2"):
            for alternate_type in ("EDGE", "PULSe", "SLOPe", "VIDEO"):
                expected = {"source": source, "type": alternate_type}

                def run(source=source, alternate_type=alternate_type):
                    _scope_cli(scope, "set", "trigger.mode", "ALTernation")
                    _scope_cli(scope, "set", "trigger.alternate.source", source)
                    _scope_cli(scope, "set", "trigger.alternate.type", alternate_type)
                    _scope_cli(scope, "set", "trigger.alternate.time-scale", "0.0002")
                    _scope_cli(scope, "set", "trigger.alternate.time-offset", "0")
                    observed = {
                        "source": _scope_cli(scope, "get", "trigger.alternate.source"),
                        "type": _scope_cli(scope, "get", "trigger.alternate.type"),
                        "time_scale": _number(_scope_cli(scope, "get", "trigger.alternate.time-scale")),
                    }
                    return observed, {
                        "source": observed["source"].upper().endswith(source[-1]),
                        "type": observed["type"].upper().startswith(alternate_type[:3].upper()),
                        "time_scale": math.isclose(observed["time_scale"], 0.0002, rel_tol=0.02),
                    }

                recorder.case("ds-trigger-alternate-grid", f"{source}-{alternate_type}", expected, run)

        # Holdoff, coupling, sweep and sensitivity are shared trigger controls.
        for trigger_mode in ("EDGE", "PULSE", "SLOPE"):
            for coupling in ("DC", "AC", "HF", "LF"):
                expected = {"mode": trigger_mode, "coupling": coupling}

                def run(trigger_mode=trigger_mode, coupling=coupling):
                    _scope_cli(scope, "set", "trigger.coupling", coupling, "--mode", trigger_mode)
                    readback = _scope_cli(scope, "get", "trigger.coupling", "--mode", trigger_mode)
                    return {"readback": readback}, {"readback": readback.strip().upper() == coupling}

                recorder.case("ds-trigger-common-grid", f"{trigger_mode}-{coupling}", expected, run)
        for holdoff in (0.0000005, 0.001, 0.1, 1.0):
            expected = {"holdoff_s": holdoff}

            def run(holdoff=holdoff):
                _scope_cli(scope, "set", "trigger.holdoff", _decimal(holdoff))
                readback = _number(_scope_cli(scope, "get", "trigger.holdoff"))
                return {"readback": readback}, {"readback": math.isclose(readback, holdoff, rel_tol=0.03, abs_tol=1e-8)}

            recorder.case("ds-trigger-common-grid", f"holdoff-{holdoff:g}s", expected, run)

        # MATH/FFT expose raw display bytes only on this model. Validate the
        # operation/readback and that each exported source contains real data.
        generator.write("APPLy:SINusoid 1000,2,0")
        generator.write("APPLy:SINusoid:CH2 2000,2,0")
        _write_all(scope, [
            ":CHANnel1:COUPling DC", ":CHANnel2:COUPling DC",
            ":CHANnel1:SCALe 0.5", ":CHANnel2:SCALe 0.5",
            ":TIMebase:SCALe 0.0002", ":MATH:DISPlay ON", ":RUN",
        ])
        time.sleep(0.5)
        with tempfile.TemporaryDirectory(prefix="ds1152e-math-") as directory:
            temp = Path(directory)
            for operation in ("A+B", "A-B", "AB"):
                expected = {"operation": operation}

                def run(operation=operation):
                    _scope_cli(scope, "set", "math.operation", operation)
                    path = temp / f"math-{operation.replace('*', 'x').replace('+', 'p').replace('-', 'm')}.bin"
                    _scope_cli(scope, "waveform", "--source", "math", "--points-mode", "maximum", "--format", "bin", "--output", str(path), "--stop")
                    raw = path.read_bytes()
                    readback = _scope_cli(scope, "get", "math.operation")
                    return {"readback": readback, "points": len(raw), "raw_span": max(raw) - min(raw), "unique_values": len(set(raw))}, {
                        "operation": readback.replace("*", "").strip().upper() == operation.replace("*", "").strip().upper(),
                        "nonempty": len(raw) >= 500,
                        "varying_data": len(set(raw)) >= 8,
                    }

                recorder.case("ds-math-operations", operation, expected, run)

            _scope_cli(scope, "set", "math.operation", "FFT")
            _scope_cli(scope, "set", "math.fft-display", "ON")
            for carrier in (1_000, 5_000, 10_000):
                expected = {"operation": "FFT", "carrier_hz": carrier}

                def run(carrier=carrier):
                    generator.write(f"APPLy:SINusoid {carrier},2,0")
                    scope.write(":DISPlay:CLEar")
                    scope.write(":RUN")
                    time.sleep(2.0)
                    path = temp / f"fft-{carrier}.bin"
                    _scope_cli(scope, "waveform", "--source", "fft", "--points-mode", "maximum", "--format", "bin", "--output", str(path), "--stop")
                    raw = path.read_bytes()
                    readback = _scope_cli(scope, "get", "math.operation")
                    display = _scope_cli(scope, "get", "math.fft-display")
                    return {"readback": readback, "display": display, "points": len(raw), "raw_span": max(raw) - min(raw), "unique_values": len(set(raw))}, {
                        "operation": readback.strip().upper() == "FFT",
                        "display": display.strip().upper() == "ON",
                        "nonempty": len(raw) >= 500,
                        "spectrum_structure": len(set(raw)) >= 8 and max(raw) - min(raw) >= 10,
                    }

                recorder.case("ds-fft-grid", f"{carrier}hz", expected, run)


def cli_robustness(recorder: Recorder) -> None:
    for index in range(10):
        recorder.case("cli-repeated-sessions", f"dg-config-{index}", {"model": "DG1022"}, lambda: (
            json.loads(_cli("dg1022", "config")),
            {"identity": "DG1022" in json.loads(_cli("dg1022", "config"))["identity"]},
        ))
        recorder.case("cli-repeated-sessions", f"ds-config-{index}", {"model": "DS1152E"}, lambda: (
            json.loads(_cli("rigol", "config", cwd=DS_ROOT)),
            {"identity": "DS1152E" in json.loads(_cli("rigol", "config", cwd=DS_ROOT))["identity"]},
        ))

    # Exercise the DS numeric-parser workaround with exponent and fixed forms.
    for value, expected in (("2e-06", 0.000002), ("5e-05", 0.00005), ("0.0002", 0.0002), ("1e-03", 0.001)):
        def run(value=value, expected=expected):
            _cli("rigol", "set", "timebase.scale", value, cwd=DS_ROOT)
            readback = _number(_cli("rigol", "get", "timebase.scale", cwd=DS_ROOT))
            return {"readback": readback}, {"exact_step": math.isclose(readback, expected, rel_tol=0.001)}

        recorder.case("cli-numeric-formats", value, {"seconds_per_div": expected}, run)

    invalid_commands = (
        ("dg-invalid-channel", "dg1022", ("set", "voltage.amplitude", "2", "--channel", "3"), ROOT),
        ("dg-invalid-command", "dg1022", ("set", "not.a.command", "1"), ROOT),
        ("dg-invalid-mod-option", "dg1022", ("modulate", "am", "--deviation", "100"), ROOT),
        ("ds-invalid-channel", "rigol", ("set", "channel.scale", "1", "--channel", "3"), DS_ROOT),
        ("ds-digital-only", "rigol", ("get", "logic.display"), DS_ROOT),
        ("ds-reset-confirmation", "rigol", ("action", "general.reset"), DS_ROOT),
        ("ds-unsupported-mode", "rigol", ("get", "trigger.level", "--mode", "SLOPE"), DS_ROOT),
    )
    for name, executable, args, cwd in invalid_commands:
        expected = {"nonzero_exit": True, "diagnostic": True}

        def run(executable=executable, args=args, cwd=cwd):
            code, error = _cli_failure(executable, *args, cwd=cwd)
            return {"exit_code": code, "stderr": error}, {"nonzero_exit": code != 0, "diagnostic": error.startswith("error:") or "usage:" in error}

        recorder.case("cli-invalid-inputs", name, expected, run)

    with tempfile.TemporaryDirectory(prefix="cli-batch-") as directory:
        temp = Path(directory)
        dg_batch = temp / "dg.scpi"
        dg_batch.write_text("# acceptance\nFREQuency 1234\nFREQuency?\nVOLTage 1.5\nVOLTage?\n")
        ds_batch = temp / "ds.scpi"
        ds_batch.write_text("# acceptance\n:CHANnel1:SCALe 0.5\n:CHANnel1:SCALe?\n:TIMebase:SCALe 0.0002\n:TIMebase:SCALe?\n")
        recorder.case("cli-batch", "dg-write-query", {"frequency": 1234, "amplitude": 1.5}, lambda: (
            {"stdout": _cli("dg1022", "batch", str(dg_batch))},
            {"responses": "1.234000e+03" in _cli("dg1022", "batch", str(dg_batch)) and "1.500000e+00" in _cli("dg1022", "batch", str(dg_batch))},
        ))
        recorder.case("cli-batch", "ds-write-query", {"scale": 0.5, "timebase": 0.0002}, lambda: (
            {"stdout": _cli("rigol", "batch", str(ds_batch), cwd=DS_ROOT)},
            {"responses": "5.000e-01" in _cli("rigol", "batch", str(ds_batch), cwd=DS_ROOT) and "2.000e-04" in _cli("rigol", "batch", str(ds_batch), cwd=DS_ROOT)},
        ))


GROUPS = {
    "waveforms": waveform_grid,
    "levels-shapes": level_and_shape_grid,
    "dg-advanced": dg_advanced,
    "ds-core": ds_core,
    "ds-triggers-math": ds_triggers_math,
    "robustness": cli_robustness,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Connected DG1022/DS1152E functional acceptance")
    parser.add_argument("group", choices=tuple(GROUPS) + ("all",))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = time.time()
    recorder = Recorder()
    output = args.output or ROOT / "validation" / f"{args.group}.json"
    try:
        selected = GROUPS.values() if args.group == "all" else (GROUPS[args.group],)
        for group in selected:
            group(recorder)
    finally:
        restore_baseline()
        recorder.write(output, started)
    return 0 if all(item.status == "pass" for item in recorder.results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
