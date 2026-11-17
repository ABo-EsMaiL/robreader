"""
live.py - Read the live Rob Run process and dump the entity graph.

    python tools/kapi/live.py --pid 1234
    python tools/kapi/live.py --pid 1234 --cam
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kapi.backend import MemoryBackend  # noqa: E402
from kapi.il2cpp import Il2Cpp, dictionary_entries  # noqa: E402
from kapi.probe import LocalReader  # noqa: E402
from kapi.rob_run import Off, RobRunReader  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--dump", default="",
                    help="read from a process dump file instead of a live process")
    ap.add_argument("--cam", action="store_true", help="also dump the camera")
    ap.add_argument("--driver", action="store_true",
                    help="read through our kernel driver (needed for an "
                         "anti-cheat protected game)")
    args = ap.parse_args()

    if args.dump:
        from kapi.dump_backend import DumpBackend
        mem: MemoryBackend = DumpBackend(args.dump)
        print(f"=== dump ===\n  {args.dump}\n  {mem.summary()}")
    elif args.driver:
        from kapi.kdriver_backend import DriverBackend
        mem = DriverBackend(args.pid)
        print(f"=== kernel driver ===\n  \\\\.\\RobReader -> pid {args.pid}")
    else:
        if not args.pid:
            print("--pid or --dump or --driver is required")
            return 2
        mem = LocalReader(args.pid)
    reader = RobRunReader(mem)
    il2cpp = Il2Cpp(mem)
    try:
        print("=== modules ===")
        for name in ("GameAssembly.dll", "UnityPlayer.dll"):
            try:
                base, size = mem.module_base(name)
                print(f"  {name:20} 0x{base:012X}  ({size:#x})")
            except Exception as exc:
                print(f"  {name:20} NOT FOUND ({exc})")

        print("\n=== root ===")
        game = reader.find_game()
        print(f"  Game.Game            0x{game:012X}")
        klass = mem.u64(game)
        ns_ptr = mem.u64(klass + 0x18)
        name_ptr = mem.u64(klass + 0x10)
        print(f"  Il2CppClass          0x{klass:012X}  "
              f"({mem.cstr(ns_ptr) if ns_ptr else ''}.{mem.cstr(name_ptr) if name_ptr else '?'})")

        gm = reader.game_model(game)
        print(f"  GameModel            0x{gm:012X}")
        bm = reader.battle_model(game)
        print(f"  BattleModel          0x{bm:012X}")
        em = reader.entities_model(game)
        print(f"  BattleEntitiesModel  0x{em:012X}")

        if not em:
            print("\n  BattleEntitiesModel is null - no battle loaded.")
            print("  (start a match and run this again)")
            return 2

        d = mem.u64(em + Off.ENTITIES_MODELS)
        print(f"  entity dictionary    0x{d:012X}  count="
              f"{mem.i32(d + 0x20) if d else '?'}")

        print("\n=== entities ===")
        names = reader.read_names(game)
        if names:
            print(f"  slots/names: {len(names)}")
        n = 0
        for eid, model in dictionary_entries(mem, d):
            info = reader.read_character(model, eid)
            nick, clan = names.get(eid, (None, None))
            info.name = nick
            info.clan = clan
            n += 1
            print(f"  {info}")
        if n == 0:
            print("  (dictionary empty - no other entities loaded yet)")
        else:
            print(f"\n  {n} entity/entities read")

        if names:
            print("\n=== slots / all names ===")
            for eid, (nick, clan) in sorted(names.items()):
                who = f"[{clan}]{nick}" if clan else (nick or "?")
                print(f"  id={eid:<6} {who}")

        lp = reader.local_player(game)
        print(f"\n  local PlayerEntityModel  0x{lp:012X}")
        print(f"  local BattleCharacterModel 0x{reader.local_character(game):012X}")

        if args.cam:
            cam = reader.read_camera(game)
            print(f"\n=== camera ===\n  pos={cam.position}\n  fwd={cam.forward}\n"
                  f"  right={cam.right}\n  up={cam.up}")

        # quick sanity: does the GameAssembly still match our dump?
        # Game.Game.get_GameModel RVA from output-new/dump.cs (returns
        # [rcx+0xD0], i.e. Off.GAME_GAME_MODEL).
        try:
            raw = mem.read(mem.module_base("GameAssembly.dll")[0] + 0x910F00, 8)
            print(f"\n  get_GameModel bytes = {raw.hex(' ')} "
                  f"{'OK' if raw == bytes.fromhex('488b81d0000000c3') else 'MISMATCH'}")
        except Exception as exc:
            print(f"\n  byte check failed: {exc}")
        return 0
    finally:
        mem.close()


if __name__ == "__main__":
    raise SystemExit(main())
