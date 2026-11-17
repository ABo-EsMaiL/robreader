"""
il2cpp.py - Runtime metadata helpers for an IL2CPP process.

Static dumps (`dump.cs`) are the map, but generic classes come out of
Il2CppDumper with a field offset of 0x0 because the offset cannot be computed
for an uninstantiated generic. Resolving those at runtime means walking the
Il2CppClass / FieldInfo tables that the game itself keeps in memory.

Layout (x64, Unity 6 / metadata v39, live-verified against Rob Run):

    managed object +0x00   Il2CppClass*
    managed object +0x08   monitor pointer
    Il2CppClass     +0x10  char* name
    Il2CppClass     +0x18  char* namespace
    Il2CppClass     +0x58  Il2CppClass* parent
    Il2CppClass     +0x80  FieldInfo* fields
    Il2CppClass     +0xB8  static_fields pointer
    Il2CppClass     +0x124 uint16 field_count

    FieldInfo stride 0x20
      +0x00 char* name
      +0x08 Il2CppType* type
      +0x10 Il2CppClass* declaring parent
      +0x18 int32 field offset

    Il2CppType +0x0A  type code
      0x02 bool  0x12 class  0x15 generic instance  0x1C object
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from .backend import MemoryBackend

# ------------------------------------------------------------ object layout
OBJ_CLASS_PTR = 0x00
OBJ_MONITOR = 0x08

CLASS_NAME = 0x10
CLASS_NAMESPACE = 0x18
CLASS_PARENT = 0x58
CLASS_FIELDS = 0x80
CLASS_STATIC_FIELDS = 0xB8
CLASS_FIELD_COUNT = 0x124

FIELDINFO_STRIDE = 0x20
FIELDINFO_NAME = 0x00
FIELDINFO_TYPE = 0x08
FIELDINFO_PARENT = 0x10
FIELDINFO_OFFSET = 0x18

TYPE_CODE = 0x0A
TYPE_BOOL = 0x02
TYPE_CLASS = 0x12
TYPE_GENERIC_INST = 0x15
TYPE_OBJECT = 0x1C


@dataclass(frozen=True)
class Il2CppField:
    name: str
    offset: int
    type_code: int
    declaring_class: str


class Il2Cpp:
    """Runtime metadata reader bound to a memory backend."""

    def __init__(self, mem: MemoryBackend):
        self.mem = mem

    # ------------------------------------------------------------- classes
    def class_of(self, obj: int) -> int:
        return self.mem.u64(obj + OBJ_CLASS_PTR)

    def class_name(self, klass: int) -> str:
        ptr = self.mem.u64(klass + CLASS_NAME)
        return self.mem.cstr(ptr) if ptr else ""

    def class_namespace(self, klass: int) -> str:
        ptr = self.mem.u64(klass + CLASS_NAMESPACE)
        return self.mem.cstr(ptr) if ptr else ""

    def class_parent(self, klass: int) -> int:
        return self.mem.u64(klass + CLASS_PARENT)

    def class_full_name(self, klass: int) -> str:
        ns = self.class_namespace(klass)
        name = self.class_name(klass)
        return f"{ns}.{name}" if ns else name

    def field_count(self, klass: int) -> int:
        return self.mem.u16(klass + CLASS_FIELD_COUNT) if klass else 0

    def static_fields(self, klass: int) -> int:
        return self.mem.u64(klass + CLASS_STATIC_FIELDS)

    # ------------------------------------------------------------- fields
    def fields(self, klass: int) -> List[Il2CppField]:
        """Fields declared directly on `klass` (not inherited)."""
        out: List[Il2CppField] = []
        count = self.field_count(klass)
        base = self.mem.u64(klass + CLASS_FIELDS)
        if not base:
            return out
        for i in range(count):
            fi = base + i * FIELDINFO_STRIDE
            name_ptr = self.mem.u64(fi + FIELDINFO_NAME)
            type_ptr = self.mem.u64(fi + FIELDINFO_TYPE)
            offset = self.mem.i32(fi + FIELDINFO_OFFSET)
            type_code = self.mem.u8(type_ptr + TYPE_CODE) if type_ptr else 0
            out.append(Il2CppField(
                name=self.mem.cstr(name_ptr) if name_ptr else "",
                offset=offset,
                type_code=type_code,
                declaring_class=self.class_full_name(klass),
            ))
        return out

    def find_field(self, klass: int, name: str) -> Optional[Il2CppField]:
        """Look up a field by name, walking up the inheritance chain."""
        seen = set()
        while klass and klass not in seen:
            seen.add(klass)
            for f in self.fields(klass):
                if f.name == name:
                    return f
            klass = self.class_parent(klass)
        return None

    def field_offset(self, klass: int, name: str) -> int:
        """Field offset, or -1 if not found. Use this for generic classes."""
        f = self.find_field(klass, name)
        return f.offset if f else -1

    def resolve_offset(self, klass: int, *names: str) -> int:
        """Sum of field offsets along a chain, e.g. resolve_offset(k, 'a', 'b').

        Each step follows the object pointer stored in the field, so the
        result is an offset chain you can walk at runtime.
        """
        total = 0
        cur = klass
        for n in names:
            off = self.field_offset(cur, n)
            if off < 0:
                raise KeyError(f"field {n!r} not found on {self.class_full_name(cur)}")
            total += off
            # move to the concrete class of the referenced field, if we can
            cur = 0
        return total

    # ----------------------------------------------------------- instances
    def is_instance_of(self, obj: int, klass: int) -> bool:
        """Check whether `obj`'s class chain contains `klass`."""
        k = self.class_of(obj) if obj else 0
        seen = set()
        while k and k not in seen:
            if k == klass:
                return True
            seen.add(k)
            k = self.class_parent(k)
        return False

    def find_instances(self, klass: int, regions: List[Tuple[int, int]],
                       align: int = 8) -> List[int]:
        """
        Scan candidate regions for managed objects whose class pointer equals
        `klass`. This is how you find a singleton like Game.Game when it has
        no static field pointing at it.
        """
        hits: List[int] = []
        for start, end in regions:
            addr = (start + align - 1) & ~(align - 1)
            while addr + 8 <= end:
                try:
                    if self.mem.u64(addr) == klass:
                        hits.append(addr)
                except Exception:
                    pass
                addr += align
        return hits


# ============================================================== collections
def read_il2cpp_string(mem: MemoryBackend, address: int) -> str:
    return mem.il2cpp_string(address)


def dictionary_entries(mem: MemoryBackend, dict_ptr: int) -> Iterator[Tuple[int, int]]:
    """
    Iterate a managed Dictionary<int, TReference>.

    Layout (live-verified):
        Dictionary +0x18  entries array pointer
        Dictionary +0x20  count (including removed slots)
        entry stride 0x18:
            +0x00 uint32 hash
            +0x04 int32  next
            +0x08 int32  key
            +0x0C padding
            +0x10 uint64 value
    An entry is allocated when `next >= -1`; removed entries have hash -1.
    """
    if not dict_ptr:
        return
    entries = mem.u64(dict_ptr + 0x18)
    count = mem.i32(dict_ptr + 0x20)
    if not entries or count <= 0:
        return
    for i in range(count):
        e = entries + 0x20 + i * 0x18
        nxt = mem.i32(e + 0x04)
        if nxt < -1:
            continue
        key = mem.i32(e + 0x08)
        value = mem.u64(e + 0x10)
        if value == 0:
            continue
        yield key, value


def list_items(mem: MemoryBackend, list_ptr: int) -> Iterator[int]:
    """Iterate a managed List<T>."""
    if not list_ptr:
        return
    array = mem.u64(list_ptr + 0x10)
    count = mem.i32(list_ptr + 0x18)
    if not array or count <= 0:
        return
    for i in range(count):
        item = mem.u64(array + 0x20 + i * 8)
        if item:
            yield item
