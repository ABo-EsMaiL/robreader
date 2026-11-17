"""
dump_backend.py - A MemoryBackend that reads a Windows user-mode dump file.

Because the whole project already speaks "MemoryBackend", pointing it at a
dump means every offset, pointer chain and reader we wrote keeps working
against a snapshot of the live game - with zero kernel code of our own.

Supported: minidump format (full user dumps and live dumps produced by
Process Hacker / System Informer / Task Manager).

    python tools/kapi/live.py --dump game.dmp
"""
from __future__ import annotations

import bisect
import ctypes
import struct
from typing import Dict, List, Optional, Tuple

from .backend import MemoryBackend

MDMP = b"MDMP"
MEMORY_LIST = 5
MEMORY64_LIST = 9
MODULE_LIST = 4


class Region:
    __slots__ = ("start", "end", "offset")

    def __init__(self, start: int, end: int, offset: int):
        self.start = start
        self.end = end
        self.offset = offset


class DumpBackend(MemoryBackend):
    """Read-only view of a minidump as if it were a live process."""

    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as fh:
            self.data = fh.read()
        if self.data[:4] != MDMP:
            raise ValueError(f"{path} is not a minidump (no MDMP header)")
        self.regions: List[Region] = []
        self.modules: List[Tuple[int, int, str]] = []
        self._starts: List[int] = []
        self._parse()

    # ------------------------------------------------------------ parsing
    def _parse(self) -> None:
        (n_dirs,) = struct.unpack_from("<I", self.data, 8)
        (dir_rva,) = struct.unpack_from("<I", self.data, 12)
        dirs = []
        for i in range(n_dirs):
            stype, size, rva = struct.unpack_from("<III", self.data, dir_rva + i * 12)
            dirs.append((stype, size, rva))

        # the memory blob of a MEMORY64_LIST starts right after every other
        # stream's data - that is how dbghelp lays the file out
        end_of_streams = 0
        for stype, size, rva in dirs:
            end_of_streams = max(end_of_streams, rva + size)
        self.memory_base = end_of_streams

        for stype, size, rva in dirs:
            if stype == MEMORY64_LIST:
                # MINIDUMP_MEMORY64_LIST { ULONG64 NumberOfMemoryRanges;
                #                            RVA64 BaseRva;
                #                            MINIDUMP_MEMORY_DESCRIPTOR64[] }
                (count,) = struct.unpack_from("<Q", self.data, rva)
                (base_rva,) = struct.unpack_from("<Q", self.data, rva + 8)
                desc = rva + 16
                file_off = base_rva
                for i in range(count):
                    start, size64 = struct.unpack_from(
                        "<QQ", self.data, desc + i * 16)
                    self.regions.append(Region(start, start + size64, file_off))
                    file_off += size64
            elif stype == MEMORY_LIST:
                (count,) = struct.unpack_from("<I", self.data, rva)
                base_rva = rva + 4
                for i in range(count):
                    off = base_rva + i * 16
                    start, size32, rva32 = struct.unpack_from("<III", self.data, off)
                    self.regions.append(Region(start, start + size32, rva32))
            elif stype == MODULE_LIST:
                (count,) = struct.unpack_from("<I", self.data, rva)
                base_rva = rva + 4
                for i in range(count):
                    off = base_rva + i * 108
                    base, msize, _csum, _ts, name_rva = \
                        struct.unpack_from("<QIIII", self.data, off)
                    (nlen,) = struct.unpack_from("<I", self.data, name_rva)
                    name = self.data[name_rva + 4:name_rva + 4 + nlen].decode(
                        "utf-16-le", "replace").rstrip("\x00")
                    self.modules.append((base, msize, name))

        self.regions.sort(key=lambda r: r.start)
        self._starts = [r.start for r in self.regions]

    # ----------------------------------------------------------- access
    def _find(self, address: int) -> Optional[Region]:
        i = bisect.bisect_right(self._starts, address) - 1
        if i < 0:
            return None
        r = self.regions[i]
        if address < r.end:
            return r
        return None

    def attach(self, pid: int) -> None:
        pass

    def read(self, address: int, size: int) -> bytes:
        r = self._find(address)
        if r is None:
            raise OSError(f"address 0x{address:X} is not in the dump")
        if address + size > r.end:
            raise OSError(f"read of {size} bytes at 0x{address:X} "
                          f"crosses a region boundary")
        off = r.offset + (address - r.start)
        return self.data[off:off + size]

    def write(self, address: int, data: bytes) -> int:
        raise PermissionError("a dump is read-only")

    def query(self, address: int):
        r = self._find(address)
        if r is None:
            raise OSError("not mapped")
        return type("Q", (), {"present": 1, "protection": 4,
                               "page_base": address & ~0xFFF,
                               "reserved": 0})()

    def module_base(self, name: str) -> Tuple[int, int]:
        for base, size, mod in self.modules:
            if mod.lower() == name.lower():
                return base, size
        raise KeyError(f"{name} not in the dump module list")

    def close(self) -> None:
        pass

    # -------------------------------------------------------- reporting
    def summary(self) -> str:
        total = sum(r.end - r.start for r in self.regions)
        return (f"{len(self.regions)} regions, {total/1024/1024:.1f} MB, "
                f"{len(self.modules)} modules")
