"""
kdriver_backend.py - Plug the kernel driver into the existing reader.

`RobRunReader` only needs an object with read()/u32()/u64()/f32()...  so a
backend that forwards to the driver is enough to read a game that Easy
Anti-Cheat protects.

    python tools/kapi/live.py --pid 1234 --cam --driver
"""
from __future__ import annotations

import os
import struct
import sys
from typing import Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kapi.backend import MemoryBackend  # noqa: E402
from kapi.kdriver import DriverReader     # noqa: E402


class DriverBackend(MemoryBackend):
    """Reads target memory through \\\\ .\\RobReader."""

    def __init__(self, pid: int, device: str = r"\\.\RobReader"):
        self.pid = pid
        self.device = device
        self.reader = DriverReader(device)
        if not self.reader.open():
            raise PermissionError(
                f"cannot open {device} - is the driver loaded? "
                "Run tools\\admin\\install_robreader.ps1")

    def attach(self, pid: int) -> None:
        self.pid = pid

    def read(self, address: int, size: int) -> bytes:
        data = self.reader.read(self.pid, address, size)
        if len(data) < size:
            raise OSError(f"short read at 0x{address:X}: "
                          f"{len(data)} of {size} bytes")
        return data

    def write(self, address: int, data: bytes) -> int:
        raise PermissionError("this driver is read only")

    def query(self, address: int):
        raise NotImplementedError

    def module_base(self, name: str) -> Tuple[int, int]:
        """
        Find a module base by walking the target's PEB loader list.

        The PEB address comes from NtQueryInformationProcess (that part still
        works on a protected process); the loader list is then read through
        the driver.
        """
        from kapi import syscall as sc
        from kapi.rob_run import Off

        ds = sc.DirectSyscall()
        try:
            status, handle = sc.open_process(ds, self.pid,
                                            0x0400 | 0x1000)
            if status != 0:
                raise OSError(f"NtOpenProcess failed: {sc.status_text(status)}")
            st, pbi = sc.query_information_process(ds, handle.value, 0, 0x40)
            if st != 0 or len(pbi) < 0x18:
                raise OSError("NtQueryInformationProcess failed")
            peb = struct.unpack_from("<Q", pbi, 0x10)[0]
        finally:
            try:
                ds.close()
            except Exception:
                pass

        # PEB->Ldr
        ldr = self.u64(peb + 0x18)
        # PEB_LDR_DATA->InLoadOrderModuleList
        head = self.u64(ldr + 0x10)

        seen = set()
        for _ in range(1024):
            if not head or head in seen:
                break
            seen.add(head)
            entry = head
            base = self.u64(entry + 0x30)
            size = self.u32(entry + 0x40)
            # BaseDllName UNICODE_STRING: Length at +0x58, Buffer at +0x60
            # (offsets differ between builds, so probe a few candidates)
            module = ""
            for name_off in (0x58, 0x54, 0x50, 0x5C, 0x60):
                try:
                    length = self.u16(entry + name_off)
                    buffer_ptr = self.u64(entry + name_off + 8)
                    if 2 <= length <= 256 and buffer_ptr:
                        raw = self.read(buffer_ptr, length)
                        module = raw.decode("utf-16-le", "replace")
                        if module.lower().endswith(".dll"):
                            break
                        module = ""
                except Exception:
                    continue
            if module.lower() == name.lower():
                return base, size
            head = self.u64(entry)

        raise KeyError(name)

    def close(self) -> None:
        self.reader.close()
