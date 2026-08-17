from __future__ import annotations

import array
import fcntl
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import TransportError

USBTMC_IOCTL_CLEAR = 0x5B02
USBTMC_IOCTL_SET_TIMEOUT = 0x40045B0A


@dataclass(frozen=True)
class DeviceInfo:
    path: Path
    manufacturer: str
    product: str
    serial: str
    vendor_id: str
    product_id: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _device_info(node: Path) -> DeviceInfo | None:
    try:
        usb_device = (Path("/sys/class/usbmisc") / node.name / "device").resolve().parent
    except OSError:
        return None
    vendor_id = _read_text(usb_device / "idVendor").lower()
    manufacturer = _read_text(usb_device / "manufacturer")
    if vendor_id != "1ab1" and "rigol" not in manufacturer.lower():
        return None
    return DeviceInfo(
        path=node, manufacturer=manufacturer,
        product=_read_text(usb_device / "product"),
        serial=_read_text(usb_device / "serial"), vendor_id=vendor_id,
        product_id=_read_text(usb_device / "idProduct").lower(),
    )


def discover_devices() -> list[DeviceInfo]:
    return [item for node in sorted(Path("/dev").glob("usbtmc*"))
            if (item := _device_info(node)) is not None]


def choose_device(path: str | None = None, serial: str | None = None) -> DeviceInfo:
    if path is not None:
        requested = Path(path)
        node = requested.resolve() if requested.is_symlink() else requested
        item = _device_info(node)
        if item is None:
            raise TransportError(f"no RIGOL DG USBTMC device found at {path}")
        return item
    devices = discover_devices()
    if serial is not None:
        matches = [item for item in devices if item.serial == serial]
    else:
        matches = [item for item in devices if item.serial.upper().startswith("DG")]
    if not matches:
        selector = f" at {path}" if path else f" with serial {serial!r}" if serial else ""
        raise TransportError(f"no RIGOL DG USBTMC device found{selector}")
    if len(matches) > 1:
        paths = ", ".join(str(item.path) for item in matches)
        raise TransportError(f"multiple RIGOL generators found ({paths}); use --device or --serial")
    return matches[0]


class LinuxUsbtmc:
    """Dependency-free Linux USBTMC transport compatible with the DG1022."""

    def __init__(
        self,
        device: DeviceInfo,
        *,
        timeout_ms: int = 5000,
        clear_on_open: bool = False,
        query_delay_ms: float = 2.0,
        command_delay_ms: float = 100.0,
    ) -> None:
        if timeout_ms <= 0:
            raise TransportError("timeout must be positive")
        if query_delay_ms < 0:
            raise TransportError("query delay cannot be negative")
        if command_delay_ms < 0:
            raise TransportError("command delay cannot be negative")
        self.device = device
        self.timeout_ms = timeout_ms
        self.clear_on_open = clear_on_open
        self.query_delay_ms = query_delay_ms
        self.command_delay_ms = command_delay_ms
        self._fd: int | None = None

    def __enter__(self) -> "LinuxUsbtmc":  # noqa: UP037
        try:
            self._fd = os.open(self.device.path, os.O_RDWR)
            fcntl.flock(self._fd, fcntl.LOCK_EX)
            fcntl.ioctl(self._fd, USBTMC_IOCTL_SET_TIMEOUT, array.array("I", [self.timeout_ms]), True)
            # This DG1022 times out if USBTMC_IOCTL_EOM_ENABLE is issued.
            if self.clear_on_open:
                fcntl.ioctl(self._fd, USBTMC_IOCTL_CLEAR)
        except OSError as exc:
            self.close()
            if exc.errno in {1, 13}:
                raise TransportError(
                    f"permission denied opening {self.device.path}; install the udev rule or join plugdev"
                ) from exc
            raise TransportError(f"cannot initialize {self.device.path}: {exc}") from exc
        return self

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise TransportError("USBTMC session is not open")
        return self._fd

    @staticmethod
    def _encode(command: str | bytes) -> bytes:
        if isinstance(command, str):
            try:
                payload = command.encode("ascii")
            except UnicodeEncodeError as exc:
                raise TransportError("SCPI commands must contain ASCII characters only") from exc
        else:
            payload = bytes(command)
        if b"\n" in payload.rstrip(b"\r\n"):
            raise TransportError("a command cannot contain embedded newlines")
        return payload.rstrip(b"\r\n") + b"\n"

    def write(self, command: str | bytes) -> int:
        try:
            written = os.write(self.fd, self._encode(command))
        except OSError as exc:
            raise TransportError(f"USBTMC write failed: {exc}") from exc
        if self.command_delay_ms:
            time.sleep(self.command_delay_ms / 1000)
        return written

    def read(self, *, max_bytes: int = 2 * 1024 * 1024) -> bytes:
        if max_bytes <= 0:
            raise TransportError("read size must be positive")
        try:
            return os.read(self.fd, max_bytes)
        except OSError as exc:
            raise TransportError(f"USBTMC read failed: {exc}") from exc

    def query(self, command: str | bytes, *, max_bytes: int = 2 * 1024 * 1024) -> bytes:
        self.write(command)
        if self.query_delay_ms:
            time.sleep(self.query_delay_ms / 1000)
        return self.read(max_bytes=max_bytes)

    def query_text(self, command: str, *, max_bytes: int = 65536) -> str:
        data = self.query(command, max_bytes=max_bytes)
        try:
            return data.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise TransportError("instrument returned binary data to a text query") from exc
