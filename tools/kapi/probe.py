"""
probe.py - Prove (or disprove) that we can read the live game.

This is the cheapest possible test of the whole premise: it does exactly
what Cheat Engine does (OpenProcess + ReadProcessMemory + module
enumeration) but from a script, so we get a clear answer with no GUI and
no chance of misreading an error message.

    python tools/kapi/probe.py                       # find ROB RUN.exe
    python tools/kapi/probe.py --pid 1234
    python tools/kapi/probe.py --scan 0x140000000-0x200000000

Exit codes:
    0 = read worked (modules visible + GameAssembly base resolved)
    2 = process found but OpenProcess/ReadProcessMemory was denied
    3 = process not running
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kapi import win  # noqa: E402
from kapi.backend import DriverBackend, MemoryBackend  # noqa: E402
from kapi.rob_run import CLASS_TABLE_SLOT, TypeIndex  # noqa: E402

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
LIST_MODULES_ALL = 0x03


class LocalReader(MemoryBackend):
    """Plain ReadProcessMemory backend for the current target PID."""

    def __init__(self, pid: int):
        self.pid = pid
        self.handle = win.kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not self.handle:
            raise PermissionError(
                f"OpenProcess({pid}) failed with error {win.winerror()}. "
                "Run this from an elevated (Administrator) shell.")

    def attach(self, pid: int) -> None:
        pass

    def read(self, address: int, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        ok = win.kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(address),
                                            buf, size, ctypes.byref(got))
        if not ok or got.value != size:
            raise OSError(win.winerror(),
                          f"ReadProcessMemory(0x{address:X}, {size}) failed "
                          f"(got {got.value})")
        return buf.raw[:size]

    def write(self, address: int, data: bytes) -> int:
        raise PermissionError("probe is read-only")

    def query(self, address: int):
        raise NotImplementedError

    def module_base(self, name: str) -> Tuple[int, int]:
        for base, size, mod in win.list_modules(self.pid):
            if mod.lower() == name.lower():
                return base, size
        raise KeyError(name)

    def close(self) -> None:
        if self.handle:
            win.close_handle(self.handle)
            self.handle = None


def parse_region(text: str) -> Tuple[int, int]:
    lo, _, hi = text.partition("-")
    return int(lo, 0), int(hi, 0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--exe", default="ROB RUN.exe")
    ap.add_argument("--scan", action="append",
                    help="region START-END to scan for the Game.Game instance")
    ap.add_argument("--driver", default="",
                    help="use a kernel driver device instead of ReadProcessMemory")
    args = ap.parse_args()

    pid = args.pid or (win.find_pid(args.exe) or 0)
    if not pid:
        print(f"process '{args.exe}' is not running")
        return 3
    print(f"target pid = {pid}")

    mem: MemoryBackend
    if args.driver:
        mem = DriverBackend(args.driver)
        mem.attach(pid)
    else:
        try:
            mem = LocalReader(pid)
        except PermissionError as exc:
            print(f"ERROR: {exc}")
            return 2
        print("backend    = ReadProcessMemory (user mode)")

    try:
        # 1) modules
        try:
            mods = win.list_modules(pid)
            print(f"modules    = {len(mods)} visible")
            for base, size, name in mods[:8]:
                print(f"    {name:<28} 0x{base:012X}  ({size} bytes)")
            if len(mods) > 8:
                print(f"    ... and {len(mods) - 8} more")
        except Exception as exc:
            print(f"modules    = ENUMERATION FAILED ({exc})")
            mods = []

        # 2) GameAssembly base
        try:
            base, size = mem.module_base("GameAssembly.dll")
            print(f"GameAssembly.dll = 0x{base:012X} (size {size:#x})")
        except Exception as exc:
            print(f"GameAssembly.dll = NOT FOUND ({exc})")
            return 2

        # 3) sanity: read a known code byte at get_Player (RVA 0x904DA0)
        try:
            raw = mem.read(base + 0x904DA0, 8)
            expect = bytes.fromhex("488B81D0000000C3")
            ok = raw == expect
            print(f"bytes @ +0x904DA0 = {raw.hex(' ')}  "
                  f"{'OK (matches get_Player)' if ok else 'MISMATCH'}")
        except Exception as exc:
            print(f"read failed: {exc}")
            return 2

        # 4) resolve the Il2CppClass for Game.Game
        try:
            table = mem.u64(base + CLASS_TABLE_SLOT)
            klass = mem.u64(table + TypeIndex.GAME * 8)
            name_ptr = mem.u64(klass + 0x10)
            ns_ptr = mem.u64(klass + 0x18)
            name = mem.cstr(name_ptr) if name_ptr else "?"
            ns = mem.cstr(ns_ptr) if ns_ptr else ""
            print(f"class[{TypeIndex.GAME}] = 0x{klass:012X}  -> {ns}.{name}")
        except Exception as exc:
            print(f"class resolution failed: {exc}")
            return 2

        # 5) optional: scan for the Game.Game singleton
        for region in (args.scan or []):
            lo, hi = parse_region(region)
            print(f"scanning 0x{lo:X}-0x{hi:X} for the Game.Game instance ...")
            hits = []
            addr = lo
            while addr < hi:
                try:
                    if mem.u64(addr) == klass:
                        hits.append(addr)
                        if len(hits) >= 4:
                            break
                except Exception:
                    pass
                addr += 8
            print(f"  {len(hits)} candidate(s): " +
                  ", ".join(f"0x{h:X}" for h in hits))

        print("\nRESULT: memory read works.")
        return 0
    finally:
        mem.close()


if __name__ == "__main__":
    raise SystemExit(main())
