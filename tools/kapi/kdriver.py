r"""
kdriver.py - Read another process's memory through our own kernel driver.

The driver (github-repo/driver/robreader.c) is read only: it exposes a
single ioctl that copies bytes out of a target process with
MmCopyVirtualMemory in kernel mode, which is the one path Easy Anti-Cheat's
object manager callback cannot block.

    python tools/kapi/kdriver.py --pid 1234 --addr 0x7ff000000000
"""
from __future__ import annotations

import argparse
import ctypes
import os
import struct
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# CTL_CODE(FILE_DEVICE_UNKNOWN=0x22, 0x800, METHOD_BUFFERED, FILE_ANY_ACCESS)
#   = (0x22 << 16) | (0x800 << 2) | 0 = 0x22002000
IOCTL_ROB_READ = 0x22002000

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.c_void_p]
k32.CreateFileW.restype = ctypes.c_void_p
k32.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.c_void_p, ctypes.c_void_p]
k32.DeviceIoControl.restype = ctypes.c_int
k32.CloseHandle.argtypes = [ctypes.c_void_p]


class DriverReader:
    r"""Talks to \\.\RobReader."""

    def __init__(self, device: str = r"\\.\RobReader"):
        self.device = device
        self.handle = None

    def open(self) -> bool:
        self.handle = k32.CreateFileW(self.device,
                                     GENERIC_READ | GENERIC_WRITE,
                                     FILE_SHARE_READ | FILE_SHARE_WRITE,
                                     None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL,
                                     None)
        if not self.handle or self.handle == INVALID_HANDLE_VALUE:
            print(f"open {self.device} failed: winerror "
                  f"{ctypes.get_last_error()}")
            self.handle = None
            return False
        return True

    def close(self) -> None:
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = None

    def read(self, pid: int, address: int, size: int) -> bytes:
        """
        Read `size` bytes at `address` in process `pid`.

        The request and the reply share one buffer (METHOD_BUFFERED): the
        request occupies the first 24 bytes, the data follows it.  The driver
        copies the request out first, then writes the data at offset 0.
        """
        if not self.handle:
            raise OSError("driver not open")

        req = struct.pack("<IIQII", pid, address & 0xFFFFFFFF, address,
                          size, 0)
        # input 24 bytes, output size bytes, in one buffer
        buf = ctypes.create_string_buffer(24 + size)
        ctypes.memmove(buf, req, 24)
        returned = ctypes.c_uint32(0)
        ok = k32.DeviceIoControl(self.handle, IOCTL_ROB_READ,
                                 buf, 24,
                                 buf, size,
                                 ctypes.byref(returned), None)
        if not ok:
            raise OSError(f"DeviceIoControl failed: winerror "
                          f"{ctypes.get_last_error()}")
        if returned.value == 0:
            return b""
        return buf.raw[:returned.value]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--addr", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--size", type=int, default=64)
    args = ap.parse_args()

    r = DriverReader()
    if not r.open():
        return 2
    try:
        data = r.read(args.pid, args.addr, args.size)
        print(f"read {len(data)} bytes from pid {args.pid} at "
              f"{args.addr:#x}")
        print(data.hex(" "))
    finally:
        r.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
