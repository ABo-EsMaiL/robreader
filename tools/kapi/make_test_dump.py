"""
make_test_dump.py - Build a synthetic minidump to validate DumpBackend.

Not needed for the project itself - it exists so the dump parser can be
tested without waiting for a real dump.

    python tools/kapi/make_test_dump.py test.dmp
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kapi.dump_backend import DumpBackend  # noqa: E402

BASE = 0x7FF600000000
SIZE = 0x1000000
DIR_RVA = 0x1000


def build(path: str) -> None:
    payload = bytearray(SIZE)
    # the exact bytes of BattleCharacterModel.get_Player in this build
    payload[0x904DA0:0x904DA0 + 8] = bytes.fromhex("488b81d0000000c3")

    n_streams = 2
    dir_size = n_streams * 12
    blob_base = DIR_RVA + dir_size

    name = "GameAssembly.dll\0".encode("utf-16-le")
    name_rva = blob_base + 0x100

    # MINIDUMP_MEMORY64_LIST { count, BaseRva, descriptor{start,size} }
    m64 = struct.pack("<QQQQ", 1, 0, BASE, SIZE)
    mod = struct.pack("<QIIII", BASE, SIZE, 0, 0, name_rva)
    mod += b"\0" * (108 - len(mod))
    modlist = struct.pack("<I", 1) + mod

    blobs = bytearray()
    dirs = []
    for stype, data in ((9, m64), (4, modlist)):
        rva = blob_base + len(blobs)
        blobs += data
        dirs.append((stype, len(data), rva))
    # the module name string
    while blob_base + len(blobs) < name_rva:
        blobs += b"\0"
    blobs += struct.pack("<I", len(name)) + name

    payload_rva = blob_base + len(blobs)
    # patch BaseRva inside the MEMORY64_LIST now that we know the layout
    struct.pack_into("<Q", blobs, 8, payload_rva)

    header = b"MDMP"
    header += struct.pack("<IIII", 0xA793, n_streams, DIR_RVA, 0)
    header += struct.pack("<IIQ", 0, 0, 0)
    dir_bytes = b"".join(struct.pack("<III", t, s, r) for t, s, r in dirs)

    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(b"\0" * (DIR_RVA - len(header)))     # pad up to DIR_RVA
        fh.write(dir_bytes)                            # directory AT DIR_RVA
        fh.write(blobs)
        fh.write(payload)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "test.dmp"
    build(out)
    b = DumpBackend(out)
    print(f"wrote {out}")
    print(f"  {b.summary()}")
    base, size = b.module_base("GameAssembly.dll")
    print(f"  GameAssembly.dll = 0x{base:X}")
    raw = b.read(base + 0x904DA0, 8)
    print(f"  bytes @ +0x904DA0 = {raw.hex(' ')} "
          f"{'OK' if raw == bytes.fromhex('488b81d0000000c3') else 'MISMATCH'}")
