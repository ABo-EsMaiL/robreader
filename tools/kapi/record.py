"""
record.py - Continuously record every player in the battle.

The server terminates the battle as soon as it notices the missing
anti-cheat session, so there is a window between "joined room" and the
kick. This records that window at high frequency into a JSONL file, so the
whole match can be reconstructed afterwards.

    python tools/kapi/record.py --pid 1234 --out match.jsonl
    python tools/kapi/record.py --pid 1234 --out match.jsonl --hz 20
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kapi.probe import LocalReader  # noqa: E402
from kapi.rob_run import Off, RobRunReader  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--exe", default="ROB RUN.exe",
                    help="find the process by name and wait for it")
    ap.add_argument("--out", default="match.jsonl")
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--seconds", type=float, default=600)
    args = ap.parse_args()

    pid = args.pid
    if not pid:
        import psutil
        print(f"[+] waiting for {args.exe} ...", flush=True)
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if (p.info["name"] or "").lower() == args.exe.lower():
                        pid = p.info["pid"]
                        break
                except Exception:
                    pass
            if pid:
                break
            time.sleep(0.25)
        if not pid:
            print("[!] the process never appeared")
            return 1
        print(f"[+] found pid {pid}")

    mem = LocalReader(pid)
    reader = RobRunReader(mem)
    out = open(args.out, "a", encoding="utf-8", buffering=1)
    interval = 1.0 / max(args.hz, 0.1)
    deadline = time.time() + args.seconds
    game = 0
    print(f"[+] recording pid {args.pid} -> {args.out}")

    try:
        while time.time() < deadline:
            tick = time.time()
            try:
                if not game:
                    game = reader.find_game()
            except Exception:
                game = 0
            if game:
                try:
                    chars = list(reader.characters(game))
                except Exception:
                    chars = []
                for eid, bcm in chars:
                    info = reader.read_character(bcm, eid)
                    rec = {
                        "t": round(tick, 3),
                        "wall": datetime.now().isoformat(timespec="milliseconds"),
                        "id": info.entity_id,
                        "addr": hex(info.address),
                        "pos": [round(v, 3) for v in info.position],
                        "vel": [round(v, 3) for v in info.velocity],
                        "yaw": round(info.yaw, 2),
                        "pitch": round(info.pitch, 2),
                        "hp": info.max_health,
                        "dead": info.is_dead,
                        "role": info.role,
                    }
                    out.write(json.dumps(rec) + "\n")
                if chars:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                          f"{len(chars)} characters", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        out.close()
        print("[+] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
