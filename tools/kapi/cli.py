"""
cli.py - Command line front end for the Rob Run reader.

    python -m tools.kapi.cli selftest
        Runs the whole chain against an in-memory mock. No driver, no game,
        no admin rights. Proves the offset map and the pointer logic.

    python -m tools.kapi.cli list --device "\\\\.\\RobRunMem" --pid 1234
        Reads the live game through the kernel driver.

    python -m tools.kapi.cli watch --device "\\\\.\\RobRunMem" --pid 1234
        Same, refreshed a few times a second.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Optional, Tuple

if __package__ in (None, ""):  # allow "python cli.py"
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from tools.kapi import backend as _b
    from tools.kapi import rob_run as _r
else:
    from . import backend as _b
    from . import rob_run as _r


def _parse_region(text: str) -> Tuple[int, int]:
    lo, _, hi = text.partition("-")
    return int(lo, 0), int(hi, 0)


def cmd_selftest(args) -> int:
    """Exercise the reader against a synthetic process."""
    mem = _b.MockBackend()
    game, base = _r.build_robrun_fixture(mem, characters=args.characters)
    reader = _r.RobRunReader(mem, game_base=base, unity_base=base + 0x100000000)

    print(f"mock process: Game.Game @ 0x{game:X}, GameAssembly @ 0x{base:X}")
    print()
    print("entities:")
    for eid, entity in reader.characters(game):
        print("  " + str(reader.read_character(entity, eid)))
    print()
    cam = reader.read_camera(game)
    print(f"camera: pos={cam.position} forward={cam.forward}")
    print()
    local = reader.local_character(game)
    print(f"local character: {reader.read_character(local)}")
    print()
    print("OK - pointer chains resolve end to end.")
    return 0


def cmd_list(args) -> int:
    mem = _b.DriverBackend(args.device)
    mem.attach(args.pid)
    reader = _r.RobRunReader(mem)
    regions = [_parse_region(r) for r in args.region] or None
    game = reader.find_game(regions=regions)
    print(f"Game.Game @ 0x{game:X}")
    for eid, entity in reader.characters(game):
        print("  " + str(reader.read_character(entity, eid)))
    return 0


def cmd_watch(args) -> int:
    mem = _b.DriverBackend(args.device)
    mem.attach(args.pid)
    reader = _r.RobRunReader(mem)
    regions = [_parse_region(r) for r in args.region] or None
    game = reader.find_game(regions=regions)
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print(f"--- {time.strftime('%H:%M:%S')} ---")
        for eid, entity in reader.characters(game):
            print("  " + str(reader.read_character(entity, eid)))
        time.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kapi", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("selftest", help="run against an in-memory mock")
    s.add_argument("--characters", type=int, default=3)
    s.set_defaults(func=cmd_selftest)

    for name, fn, helptext in (("list", cmd_list, "read the live game once"),
                               ("watch", cmd_watch, "read the live game continuously")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--device", default=r"\\.\RobRunMem")
        s.add_argument("--pid", type=int, required=True)
        s.add_argument("--region", action="append",
                       help="heap region as START-END (hex ok), repeatable")
        if name == "watch":
            s.add_argument("--interval", type=float, default=0.25)
        s.set_defaults(func=fn)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # surface the reason clearly
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
