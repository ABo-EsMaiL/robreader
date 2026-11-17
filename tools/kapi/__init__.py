"""
kapi - a small user-mode memory API for IL2CPP games.

Layout:
    win.py       Win32 bindings (CreateFileW / DeviceIoControl / snapshots)
    protocol.py  the IOCTL contract between user mode and kernel mode
    backend.py   MemoryBackend + DriverBackend + MockBackend + LocalBackend
    il2cpp.py    runtime metadata (Il2CppClass / FieldInfo) resolution
    rob_run.py   the Rob Run offset map and the object-graph reader
    cli.py       command line front end

Typical use with a kernel driver:

    from .backend import DriverBackend
    from .rob_run import RobRunReader

    mem = DriverBackend(r"\\\\.\\RobRunMem")
    mem.attach(pid)
    reader = RobRunReader(mem)
    game = reader.find_game(regions=[(heap_start, heap_end)])
    for eid, bcm in reader.characters(game):
        print(reader.read_character(bcm))
"""
from __future__ import annotations

from .backend import DriverBackend, LocalBackend, MemoryBackend, MockBackend
from .il2cpp import Il2Cpp, dictionary_entries
from .rob_run import CharacterInfo, Off, RobRunReader, ROLE_NAMES, TypeIndex

__all__ = [
    "DriverBackend",
    "LocalBackend",
    "MemoryBackend",
    "MockBackend",
    "Il2Cpp",
    "RobRunReader",
    "CharacterInfo",
    "Off",
    "TypeIndex",
    "ROLE_NAMES",
    "dictionary_entries",
]
