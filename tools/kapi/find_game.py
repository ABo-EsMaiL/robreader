"""
find_game.py - Locate the live Game.Game singleton in a Rob Run process.

The IL2CPP object graph is rooted at a MonoBehaviour instance. The standard
route (used by the community) is Unity's GameObjectManager:

    UnityPlayer.dll + <GOM offset>  ->  GOM
      -> node list, each node has  ->  GameObject*
           GameObject+0x50 -> char* name
           GameObject+0x20 -> Component[] , +0x30 count
           Component+0x18 -> handle, handle&~7 -> managed object
           managed+0x00 -> Il2CppClass*, class+0x10 -> class name
    the "UnityEntry" GameObject has a "UnityEntry" component
      component+0x28 -> Game.Game instance

The GOM offset differs per Unity build, so this tool tries several known
offsets and, if none work, scans UnityPlayer's data section for a plausible
GOM pointer.

Usage:
    python tools/kapi/find_game.py --pid 1234
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kapi.backend import MemoryBackend  # noqa: E402
from kapi.il2cpp import Il2Cpp  # noqa: E402
from kapi.probe import LocalReader  # noqa: E402

# Candidate offsets of the GameObjectManager pointer inside UnityPlayer.dll.
# 0x2230768 is the value the community published for a recent Rob Run build.
GOM_OFFSETS = [
    0x2230768,
    0x2230700, 0x2230770, 0x2230780, 0x2230760,
    0x22306A8, 0x2230600, 0x2230800,
    0x2230A80, 0x222F000, 0x2240000,
]

TARGET_NAMES = ("UnityEntry", "[Entry]", "Entry")


def looks_like_string(mem: MemoryBackend, ptr: int, want: str) -> bool:
    if not ptr:
        return False
    try:
        s = mem.cstr(ptr, 64)
    except Exception:
        return False
    return s == want


def try_gom(mem: MemoryBackend, unity_base: int, gom_offset: int,
            il2cpp: Il2Cpp) -> Tuple[int, str]:
    """Walk the GOM list and return the Game.Game instance."""
    gom = mem.u64(unity_base + gom_offset)
    if not gom:
        return 0, "GOM pointer is null"
    node = mem.u64(gom + 0x20)
    guard = 0
    seen = []
    while node and node != (gom + 0x18) and guard < 20000:
        guard += 1
        try:
            obj = mem.u64(node + 0x10)
            if obj:
                name_ptr = mem.u64(obj + 0x50)
                if name_ptr:
                    name = mem.cstr(name_ptr, 64)
                    seen.append(name)
                    if name in TARGET_NAMES:
                        comp = get_component(mem, obj, "UnityEntry", il2cpp)
                        if comp:
                            game = mem.u64(comp + 0x28)
                            if game:
                                return game, f"name={name} component=UnityEntry (+0x28)"
                            return 0, f"found {name} but component+0x28 is null"
                        return 0, f"found {name} but no UnityEntry component"
            node = mem.u64(node + 0x08)
        except Exception as exc:
            return 0, f"walk aborted at node {node:#x}: {exc}"
    sample = ", ".join(seen[:15]) if seen else "(no names read)"
    return 0, f"walked {guard} nodes, no target name. names seen: {sample}"


def get_component(mem: MemoryBackend, game_object: int, class_name: str,
                  il2cpp: Il2Cpp) -> int:
    comp_array = mem.u64(game_object + 0x20)
    count = mem.i32(game_object + 0x30)
    if not comp_array or count <= 0 or count > 4096:
        return 0
    for i in range(count):
        comp_ptr = mem.u64(comp_array + i * 0x10 + 0x8)
        if not comp_ptr:
            continue
        handle = mem.u64(comp_ptr + 0x18)
        managed = mem.u64(handle & ~7) if handle else 0
        if not managed:
            managed = mem.u64(comp_ptr + 0x28)
        if not managed:
            continue
        klass = mem.u64(managed)
        if not klass:
            continue
        name_ptr = mem.u64(klass + 0x10)
        if name_ptr and mem.cstr(name_ptr) == class_name:
            return managed
    return 0


def scan_unity_data(mem: MemoryBackend, unity_base: int, size: int = 0x400000,
                    step: int = 8) -> List[Tuple[int, int]]:
    """
    Look for pointers in UnityPlayer's data that behave like a GOM:
    gom+0x20 -> a node, node+0x10 -> an object, object+0x50 -> a name string.
    """
    out = []
    for off in range(0, size, step):
        try:
            p = mem.u64(unity_base + off)
        except Exception:
            continue
        if p < 0x10000 or p > 0x7FFFFFFFFFFF:
            continue
        try:
            node = mem.u64(p + 0x20)
            if node < 0x10000:
                continue
            obj = mem.u64(node + 0x10)
            if obj < 0x10000:
                continue
            name_ptr = mem.u64(obj + 0x50)
            if not name_ptr:
                continue
            name = mem.cstr(name_ptr, 32)
        except Exception:
            continue
        if name and name[0].isupper() and " " not in name:
            out.append((off, p))
            if len(out) >= 40:
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--unity-offset", type=lambda s: int(s, 0), default=0,
                    help="force a specific GOM offset")
    ap.add_argument("--scan", action="store_true",
                    help="also scan UnityPlayer's data section for GOM candidates")
    args = ap.parse_args()

    mem = LocalReader(args.pid)
    il2cpp = Il2Cpp(mem)
    try:
        unity_base, unity_size = mem.module_base("UnityPlayer.dll")
        ga_base, ga_size = mem.module_base("GameAssembly.dll")
        print(f"UnityPlayer.dll  = 0x{unity_base:X}  (size {unity_size:#x})")
        print(f"GameAssembly.dll = 0x{ga_base:X}  (size {ga_size:#x})")

        offsets = [args.unity_offset] if args.unity_offset else GOM_OFFSETS
        print("\n=== trying GOM offsets ===")
        for off in offsets:
            try:
                game, why = try_gom(mem, unity_base, off, il2cpp)
            except Exception as exc:
                game, why = 0, f"exception: {exc}"
            if game:
                print(f"  [+0x{off:X}] FOUND Game.Game @ 0x{game:X}  ({why})")
                klass = mem.u64(game)
                print(f"      Il2CppClass @ 0x{klass:X}")
                name_ptr = mem.u64(klass + 0x10)
                ns_ptr = mem.u64(klass + 0x18)
                print(f"      class = {mem.cstr(ns_ptr) if ns_ptr else ''}."
                      f"{mem.cstr(name_ptr) if name_ptr else '?'}")
                return 0
            print(f"  [0x{off:X}] {why}")

        if args.scan:
            print("\n=== scanning UnityPlayer data for GOM candidates ===")
            for off, p in scan_unity_data(mem, unity_base):
                try:
                    node = mem.u64(p + 0x20)
                    obj = mem.u64(node + 0x10)
                    nm = mem.cstr(mem.u64(obj + 0x50), 32)
                except Exception:
                    continue
                print(f"  UnityPlayer+0x{off:X} -> 0x{p:X}  first name = {nm!r}")
        return 1
    finally:
        mem.close()


if __name__ == "__main__":
    raise SystemExit(main())
