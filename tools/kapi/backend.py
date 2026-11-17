"""
backend.py - The memory backend abstraction.

`MemoryBackend` is the only thing the Rob Run reader knows about. Three
implementations:

  * DriverBackend - talks to a kernel driver over DeviceIoControl.
  * MockBackend   - a fake address space in pure Python.
  * LocalBackend  - the current process (useful for unit-testing the chains
                    against a real IL2CPP-like layout you build yourself).

The MockBackend is the important one for learning: it lets you run the whole
pointer-chain code without a kernel driver, so you can debug the *logic*
before you debug the *privilege* problem.
"""
from __future__ import annotations

import abc
import ctypes
import struct
from typing import Dict, List, Optional, Tuple

from . import protocol as P
from . import win


class MemoryError_(OSError):
    """Raised when a read fails inside the target process."""


class MemoryBackend(abc.ABC):
    """Uniform read/write access to another process's address space."""

    @abc.abstractmethod
    def attach(self, pid: int) -> None:
        """Bind to a target process."""

    @abc.abstractmethod
    def read(self, address: int, size: int) -> bytes:
        """Read `size` bytes at virtual `address`."""

    @abc.abstractmethod
    def write(self, address: int, data: bytes) -> int:
        """Write `data` at virtual `address`; returns bytes written."""

    @abc.abstractmethod
    def query(self, address: int) -> P.QueryResult:
        """Return page state/protection for `address`."""

    @abc.abstractmethod
    def module_base(self, name: str) -> Tuple[int, int]:
        """Return (base, size) of a loaded module."""

    def close(self) -> None:
        pass

    # ---------------------------------------------------------- convenience
    def bytes(self, address: int, n: int) -> bytes:
        return self.read(address, n)

    def u8(self, address: int) -> int:
        return self.read(address, 1)[0]

    def u16(self, address: int) -> int:
        return struct.unpack("<H", self.read(address, 2))[0]

    def u32(self, address: int) -> int:
        return struct.unpack("<I", self.read(address, 4))[0]
    def i32(self, address: int) -> int:
        return struct.unpack("<i", self.read(address, 4))[0]

    def u64(self, address: int) -> int:
        return struct.unpack("<Q", self.read(address, 8))[0]

    def f32(self, address: int) -> float:
        return struct.unpack("<f", self.read(address, 4))[0]

    def f32x3(self, address: int) -> Tuple[float, float, float]:
        x, y, z = struct.unpack("<fff", self.read(address, 12))
        return (x, y, z)

    def cstr(self, address: int, maxlen: int = 128) -> str:
        buf = bytearray()
        for i in range(maxlen):
            b = self.read(address + i, 1)
            if b == b"\x00":
                break
            buf += b
        return buf.decode("utf-8", "replace")

    def il2cpp_string(self, address: int) -> str:
        """IL2CPP System.String: length at +0x10, UTF-16 data at +0x14."""
        if address == 0:
            return ""
        length = self.i32(address + 0x10)
        if length <= 0 or length > 4096:
            return ""
        raw = self.read(address + 0x14, length * 2)
        return raw.decode("utf-16-le", "replace")

    def read_v(self, ptr: int, offset: int, fmt: str = "<Q") -> int:
        """Read a value at (ptr + offset) without dereferencing the result."""
        return struct.unpack(fmt, self.read(ptr + offset, struct.calcsize(fmt)))[0]

    def follow(self, ptr: int, offset: int) -> int:
        """Read the pointer stored at (ptr + offset)."""
        return self.u64(ptr + offset)


# ============================================================ DriverBackend
class DriverBackend(MemoryBackend):
    """
    User-mode client for our kernel driver.

    The driver must expose a device (e.g. \\.\\RobRunMem) and implement the
    IOCTLs declared in protocol.py. The driver itself is obtained by mapping
    it through a Microsoft-signed vulnerable driver (BYOVD), which is why
    this class only deals with the IOCTL layer.
    """

    def __init__(self, device_path: str = r"\\.\RobRunMem"):
        self.device_path = device_path
        self.handle: Optional[int] = None
        self.cr3 = 0
        self.pid = 0

    def open(self) -> None:
        self.handle = win.open_device(self.device_path)

    def attach(self, pid: int) -> None:
        if self.handle is None:
            self.open()
        req = P.AttachRequest(pid=pid, flags=0)
        res = P.AttachResult()
        win.device_io_control(self.handle, P.IOCTL_ATTACH_PROCESS,
                              req, ctypes.sizeof(req), res, ctypes.sizeof(res))
        self.cr3 = res.cr3
        self.pid = pid

    def read(self, address: int, size: int) -> bytes:
        if self.handle is None:
            raise MemoryError_("driver not opened")
        req = P.ReadRequest(address=address, size=size, reserved=0)
        out = ctypes.create_string_buffer(max(size, 1))
        got = win.device_io_control(self.handle, P.IOCTL_READ_VIRT,
                                    req, ctypes.sizeof(req), out, size)
        if got < size:
            raise MemoryError_(f"short read at 0x{address:X}: {got}/{size}")
        return out.raw[:size]

    def write(self, address: int, data: bytes) -> int:
        if self.handle is None:
            raise MemoryError_("driver not opened")
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        req = P.WriteRequest(address=address, size=len(data), reserved=0)
        # Simple convention: header first, payload after it.
        payload = ctypes.create_string_buffer(ctypes.sizeof(req) + len(data))
        ctypes.memmove(payload, req, ctypes.sizeof(req))
        ctypes.memmove(ctypes.byref(payload, ctypes.sizeof(req)), buf, len(data))
        out = ctypes.create_string_buffer(64)
        return win.device_io_control(self.handle, P.IOCTL_WRITE_VIRT,
                                     payload, ctypes.sizeof(payload), out, 64)

    def query(self, address: int) -> P.QueryResult:
        req = P.QueryRequest(address=address, reserved=0)
        res = P.QueryResult()
        win.device_io_control(self.handle, P.IOCTL_QUERY_VIRT,
                              req, ctypes.sizeof(req), res, ctypes.sizeof(res))
        return res

    def module_base(self, name: str) -> Tuple[int, int]:
        req = P.ModuleRequest(name=name.encode("ascii", "ignore")[:63])
        res = P.ModuleResult()
        win.device_io_control(self.handle, P.IOCTL_MODULE_BASE,
                              req, ctypes.sizeof(req), res, ctypes.sizeof(res))
        return res.base, res.size

    def close(self) -> None:
        if self.handle is not None:
            win.close_handle(self.handle)
            self.handle = None


# ============================================================== MockBackend
class MockBackend(MemoryBackend):
    """
    A synthetic address space so the pointer chains can be exercised offline.

    Build it with `build_robrun_fixture()` - it lays out a miniature but
    structurally faithful Game.Game -> ... -> BattleCharacterModel tree, with
    the real IL2CPP dictionary layout (entries array, 0x18 stride, hash/next/
    key/value) so the enumeration code is tested against the real thing.
    """

    BASE = 0x0000_2000_0000_0000

    def __init__(self) -> None:
        self._buf = bytearray(0x100000)
        self._top = 0x1000
        self._modules: Dict[str, Tuple[int, int]] = {}
        self.attached_pid = 0

    # -- heap helpers ----------------------------------------------------
    def alloc(self, size: int = 0x100, align: int = 0x10) -> int:
        self._top = (self._top + align - 1) & ~(align - 1)
        addr = self.BASE + self._top
        self._top += size
        return addr

    def poke(self, address: int, data: bytes) -> None:
        off = address - self.BASE
        self._buf[off:off + len(data)] = data

    def poke_u64(self, address: int, value: int) -> None:
        self.poke(address, struct.pack("<Q", value))

    def poke_i32(self, address: int, value: int) -> None:
        self.poke(address, struct.pack("<i", value))

    def poke_f32(self, address: int, value: float) -> None:
        self.poke(address, struct.pack("<f", value))

    def poke_cstr(self, address: int, text: str) -> None:
        self.poke(address, text.encode("utf-8") + b"\x00")

    def add_module(self, name: str, base: int, size: int) -> None:
        self._modules[name.lower()] = (base, size)

    # -- MemoryBackend ---------------------------------------------------
    def attach(self, pid: int) -> None:
        self.attached_pid = pid

    def read(self, address: int, size: int) -> bytes:
        off = address - self.BASE
        if off < 0 or off + size > len(self._buf):
            raise MemoryError_(f"out of mock range: 0x{address:X} (+{size})")
        return bytes(self._buf[off:off + size])

    def write(self, address: int, data: bytes) -> int:
        off = address - self.BASE
        self._buf[off:off + len(data)] = data
        return len(data)

    def query(self, address: int) -> P.QueryResult:
        return P.QueryResult(present=1, protection=win.PAGE_READWRITE,
                             page_base=address & ~0xFFF, reserved=0)

    def module_base(self, name: str) -> Tuple[int, int]:
        try:
            return self._modules[name.lower()]
        except KeyError:
            raise MemoryError_(f"module not found: {name}") from None


# ============================================================= LocalBackend
class LocalBackend(MemoryBackend):
    """Read/write the current process. Handy to unit-test chain code."""

    def attach(self, pid: int) -> None:
        if pid != 0:
            raise MemoryError_("LocalBackend only supports the current process")

    def read(self, address: int, size: int) -> bytes:
        return ctypes.string_at(address, size)

    def write(self, address: int, data: bytes) -> int:
        ctypes.memmove(address, data, len(data))
        return len(data)

    def query(self, address: int) -> P.QueryResult:
        return P.QueryResult(present=1, protection=win.PAGE_READWRITE,
                             page_base=address & ~0xFFF, reserved=0)

    def module_base(self, name: str) -> Tuple[int, int]:
        mods = win.list_modules(0)
        for base, size, mod in mods:
            if mod.lower() == name.lower():
                return base, size
        raise MemoryError_(f"module not found: {name}")
