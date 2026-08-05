import pytest

import dg1022_cli.transport as transport
from dg1022_cli.errors import TransportError
from dg1022_cli.transport import DeviceInfo, LinuxUsbtmc


def test_encode_terminates_once():
    assert LinuxUsbtmc._encode("*IDN?") == b"*IDN?\n"
    assert LinuxUsbtmc._encode(b"OUTP ON\r\n") == b"OUTP ON\n"


def test_encode_rejects_embedded_newline():
    with pytest.raises(TransportError, match="embedded newlines"):
        LinuxUsbtmc._encode("OUTP ON\nOUTP OFF")


def test_negative_query_delay_is_rejected():
    device = type("Device", (), {})()
    with pytest.raises(TransportError, match="cannot be negative"):
        LinuxUsbtmc(device, query_delay_ms=-1)
    with pytest.raises(TransportError, match="cannot be negative"):
        LinuxUsbtmc(device, command_delay_ms=-1)


def test_explicit_device_does_not_scan(monkeypatch):
    expected = DeviceInfo(transport.Path("/dev/usbtmc7"), "RIGOL", "DG", "S", "1ab1", "0588")
    monkeypatch.setattr(transport, "_device_info", lambda node: expected)
    monkeypatch.setattr(transport, "discover_devices", lambda: pytest.fail("scanned devices"))
    assert transport.choose_device("/dev/usbtmc7") == expected
