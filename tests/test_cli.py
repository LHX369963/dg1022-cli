from contextlib import contextmanager

import pytest

import dg1022_cli.cli as cli
from dg1022_cli.errors import ProtocolError


class FakeGenerator:
    def __init__(self):
        self.device = type("Device", (), {"path": "/dev/usbtmc3"})()
        self.writes = []
        self.queries = []

    def write(self, command):
        self.writes.append(command)

    def query_text(self, command, **kwargs):
        self.queries.append(command)
        if command == "*IDN?":
            return "RIGOL TECHNOLOGIES,DG1022,SERIAL,,00.02.07"
        return "SIN,1000,2,0"


@contextmanager
def fake_session(generator):
    yield generator


def test_catalog_get_and_set(monkeypatch, capsys):
    generator = FakeGenerator()
    monkeypatch.setattr(cli, "_session", lambda args: fake_session(generator))
    assert cli.main(["set", "voltage.amplitude", "2.5", "--channel", "2"]) == 0
    assert generator.writes == ["VOLTage:CH2 2.5"]
    assert cli.main(["get", "frequency.output", "--channel", "1"]) == 0
    assert generator.queries[-1] == "FREQuency?"
    assert capsys.readouterr().out.strip() == "SIN,1000,2,0"


def test_output_helper_uses_positional_apply(monkeypatch, capsys):
    generator = FakeGenerator()
    monkeypatch.setattr(cli, "_session", lambda args: fake_session(generator))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    assert cli.main(["output", "--channel", "2", "--waveform", "sine", "--frequency", "10kHz",
                     "--amplitude", "2Vpp", "--offset", "0V", "--phase", "30", "--enable"]) == 0
    assert generator.writes == [
        "APPLy:SINusoid:CH2 10kHz,2Vpp,0V",
        "PHASe:CH2 30",
        "PHASe:ALIGN",
        "PHASe:CH2 30",
        "PHASe:ALIGN",
        "OUTPut:CH2 ON",
    ]
    capsys.readouterr()


def test_dc_output_repeats_apply_to_commit_the_physical_level(monkeypatch, capsys):
    generator = FakeGenerator()
    monkeypatch.setattr(cli, "_session", lambda args: fake_session(generator))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    assert cli.main([
        "output", "--channel", "1", "--waveform", "dc", "--frequency", "1kHz",
        "--amplitude", "1Vpp", "--offset", "-0.5V", "--enable",
    ]) == 0
    assert generator.writes == [
        "APPLy:DC 1kHz,1Vpp,-0.5V",
        "APPLy:DC 1kHz,1Vpp,-0.5V",
        "OUTPut OFF",
        "OUTPut ON",
    ]
    capsys.readouterr()


def test_catalog_set_accepts_negative_values_with_unit_suffixes(monkeypatch, capsys):
    generator = FakeGenerator()
    monkeypatch.setattr(cli, "_session", lambda args: fake_session(generator))
    assert cli.main(["set", "voltage.offset", "-500mV", "--channel", "2"]) == 0
    assert generator.writes == ["VOLTage:OFFSet:CH2 -500mV"]
    capsys.readouterr()


def test_modulation_helper_orders_enable_configuration_and_final_state(monkeypatch, capsys):
    generator = FakeGenerator()
    monkeypatch.setattr(cli, "_session", lambda args: fake_session(generator))
    assert cli.main([
        "modulate", "fm", "--source", "INT", "--internal-waveform", "SIN",
        "--internal-frequency", "1kHz", "--deviation", "2kHz", "--enable",
    ]) == 0
    assert generator.writes == [
        "FM:STATe ON",
        "FM:SOURce INT",
        "FM:INTernal:FUNCtion SIN",
        "FM:INTernal:FREQuency 1kHz",
        "FM:DEViation 2kHz",
        "FM:SOURce INT",
        "FM:INTernal:FUNCtion SIN",
        "FM:INTernal:FREQuency 1kHz",
        "FM:DEViation 2kHz",
        "FM:STATe ON",
    ]
    capsys.readouterr()


def test_sweep_and_burst_helpers_emit_all_requested_parameters(monkeypatch, capsys):
    generator = FakeGenerator()
    monkeypatch.setattr(cli, "_session", lambda args: fake_session(generator))
    assert cli.main([
        "sweep-config", "--start", "200Hz", "--stop", "2kHz", "--time", "0.1",
        "--spacing", "LIN", "--trigger-source", "IMM", "--enable",
    ]) == 0
    assert generator.writes == [
        "SWEep:STATe ON",
        "FREQuency:STARt 200Hz",
        "FREQuency:STOP 2kHz",
        "SWEep:TIME 0.1",
        "SWEep:SPACing LIN",
        "TRIGger:SOURce IMM",
        "SWEep:STATe ON",
    ]
    generator.writes.clear()
    assert cli.main([
        "burst-config", "--mode", "TRIG", "--cycles", "5", "--period", "10ms",
        "--phase", "45", "--trigger-source", "BUS", "--enable",
    ]) == 0
    assert generator.writes == [
        "BURSt:STATe ON",
        "BURSt:MODE TRIG",
        "BURSt:NCYCles 5",
        "BURSt:INTernal:PERiod 10ms",
        "BURSt:PHASe 45",
        "TRIGger:SOURce BUS",
        "BURSt:STATe ON",
    ]
    capsys.readouterr()


def test_arb_upload_can_copy_select_and_enable(monkeypatch, capsys, tmp_path):
    generator = FakeGenerator()
    samples = tmp_path / "samples.txt"
    samples.write_text("-1,0,1")
    monkeypatch.setattr(cli, "_session", lambda args: fake_session(generator))
    monkeypatch.setattr(cli, "_settle_after_write", lambda command: None)
    assert cli.main([
        "arb", "upload", str(samples), "--name", "TEST_1", "--select", "--enable",
    ]) == 0
    assert generator.writes == [
        "DATA VOLATILE,-1.0,0.0,1.0",
        "DATA:COPY TEST_1",
        "FUNCtion:USER TEST_1",
        "FUNCtion USER",
        "OUTPut ON",
    ]
    capsys.readouterr()


def test_sample_validation(tmp_path):
    path = tmp_path / "wave.txt"
    path.write_text("-1, 0, 1")
    assert cli._load_samples(path, False) == ["-1.0", "0.0", "1.0"]
    path.write_text("-1, 20000")
    with pytest.raises(ProtocolError, match="outside 0..16383"):
        cli._load_samples(path, True)


def test_parse_number_handles_dg1022_ch2_prefix_and_infinity():
    assert cli._parse_number("CH2: 1.500000e+03") == 1500.0
    assert cli._parse_number("INFINITY") == "infinity"
