"""
protocol.py - The kernel <-> user-mode contract.

This is the interesting part of a driver-based memory reader: the IOCTL ABI.
Everything the user-mode side can ask the kernel side to do is expressed here
as an IOCTL code plus a fixed request structure.

Layout of an IOCTL code (Windows CTL_CODE macro):

    31            30..16        15..14        13..2            1..0
    +--------------+-------------+-------------+----------------+------+
    |  DeviceType  | Access      | Function     |  Method        | Acc  |
    +--------------+-------------+-------------+----------------+------+

`Method` decides how the kernel marshals the buffers:
    METHOD_BUFFERED  - kernel copies InBuffer into a kernel buffer, and the
                       output back into OutBuffer. Simplest to implement and
                       to reason about; the data gets copied twice.
    METHOD_NEITHER   - the raw user pointers are passed through to the
                       driver. Zero-copy, but the driver MUST probe and
                       capture them (ProbeForRead/ProbeForWrite) before use.
    METHOD_IN_DIRECT / METHOD_OUT_DIRECT - direct DMA-style I/O for large
                       transfers.

We use METHOD_BUFFERED everywhere: it is the least error-prone, and the
throughput is irrelevant for a few kilobytes per frame.
"""
from __future__ import annotations

import ctypes
from typing import Final

# ------------------------------------------------------------------ CTL_CODE
FILE_DEVICE_UNKNOWN: Final = 0x00000022


def CTL_CODE(device_type: int, function: int, method: int, access: int) -> int:
    return ((device_type & 0xFFFF) << 16) | ((access & 0x3) << 14) | \
           ((function & 0xFFF) << 2) | (method & 0x3)


METHOD_BUFFERED: Final = 0
FILE_ANY_ACCESS: Final = 0

# Our device type (arbitrary, must match the driver's IoCreateDevice call).
DEV_TYPE: Final = 0x8000 + 1  # 0x8001

# Function codes
FN_ATTACH_PROCESS: Final = 0x800
FN_DETACH_PROCESS: Final = 0x801
FN_READ_VIRT: Final = 0x802
FN_READ_PHYS: Final = 0x803
FN_WRITE_VIRT: Final = 0x804
FN_QUERY_VIRT: Final = 0x805
FN_MODULE_BASE: Final = 0x806
FN_MODULE_LIST: Final = 0x807
FN_DRIVER_VERSION: Final = 0x808

# ------------------------------------------------------------------ IOCTLs
IOCTL_ATTACH_PROCESS = CTL_CODE(DEV_TYPE, FN_ATTACH_PROCESS, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_DETACH_PROCESS = CTL_CODE(DEV_TYPE, FN_DETACH_PROCESS, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_READ_VIRT = CTL_CODE(DEV_TYPE, FN_READ_VIRT, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_READ_PHYS = CTL_CODE(DEV_TYPE, FN_READ_PHYS, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_WRITE_VIRT = CTL_CODE(DEV_TYPE, FN_WRITE_VIRT, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_QUERY_VIRT = CTL_CODE(DEV_TYPE, FN_QUERY_VIRT, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_MODULE_BASE = CTL_CODE(DEV_TYPE, FN_MODULE_BASE, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_MODULE_LIST = CTL_CODE(DEV_TYPE, FN_MODULE_LIST, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_DRIVER_VERSION = CTL_CODE(DEV_TYPE, FN_DRIVER_VERSION, METHOD_BUFFERED, FILE_ANY_ACCESS)

IOCTL_NAMES = {
    IOCTL_ATTACH_PROCESS: "ATTACH_PROCESS",
    IOCTL_DETACH_PROCESS: "DETACH_PROCESS",
    IOCTL_READ_VIRT: "READ_VIRT",
    IOCTL_READ_PHYS: "READ_PHYS",
    IOCTL_WRITE_VIRT: "WRITE_VIRT",
    IOCTL_QUERY_VIRT: "QUERY_VIRT",
    IOCTL_MODULE_BASE: "MODULE_BASE",
    IOCTL_MODULE_LIST: "MODULE_LIST",
    IOCTL_DRIVER_VERSION: "DRIVER_VERSION",
}


# ------------------------------------------------------------------ payloads
class AttachRequest(ctypes.Structure):
    """Ask the driver to resolve a PID into a kernel-usable process context."""
    _fields_ = [
        ("pid", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
    ]


class AttachResult(ctypes.Structure):
    _fields_ = [
        ("cr3", ctypes.c_uint64),       # directory table base (page aligned)
        ("image_base", ctypes.c_uint64),
        ("image_size", ctypes.c_uint64),
        ("eprocess", ctypes.c_uint64),   # kernel EPROCESS address (debug)
    ]


class ReadRequest(ctypes.Structure):
    """Translate `address` in the target's virtual space and copy it out."""
    _fields_ = [
        ("address", ctypes.c_uint64),
        ("size", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


class WriteRequest(ctypes.Structure):
    _fields_ = [
        ("address", ctypes.c_uint64),
        ("size", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


class QueryRequest(ctypes.Structure):
    _fields_ = [
        ("address", ctypes.c_uint64),
        ("reserved", ctypes.c_uint64),
    ]


class QueryResult(ctypes.Structure):
    _fields_ = [
        ("present", ctypes.c_uint32),
        ("protection", ctypes.c_uint32),
        ("page_base", ctypes.c_uint64),
        ("reserved", ctypes.c_uint64),
    ]


class ModuleRequest(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char * 64),
    ]


class ModuleResult(ctypes.Structure):
    _fields_ = [
        ("base", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
    ]


class DriverVersion(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_uint32),
        ("minor", ctypes.c_uint32),
        ("build", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


# ------------------------------------------------------------------ driver side
# Sketch of what the kernel handler looks like (C). Kept here so both sides
# of the contract live in one file and cannot drift apart.
#
# NTSTATUS DriverDispatch(PDEVICE_OBJECT Device, PIRP Irp) {
#     PIO_STACK_LOCATION st = IoGetCurrentIrpStackLocation(Irp);
#     ULONG code = st->Parameters.DeviceIoControl.IoControlCode;
#     PVOID inBuf  = Irp->AssociatedIrp.SystemBuffer;          // METHOD_BUFFERED
#     ULONG inLen  = st->Parameters.DeviceIoControl.InputBufferLength;
#     ULONG outLen = st->Parameters.DeviceIoControl.OutputBufferLength;
#     ULONG ret = 0;
#
#     switch (code) {
#     case IOCTL_ATTACH_PROCESS: {
#         if (inLen < sizeof(AttachRequest)) return STATUS_BUFFER_TOO_SMALL;
#         AttachRequest *r = (AttachRequest *)inBuf;
#         PEPROCESS e = PsLookupProcessByProcessId((HANDLE)r->pid);
#         if (!e) return STATUS_INVALID_PARAMETER;
#         AttachResult *o = (AttachResult *)inBuf;
#         o->cr3 = (UINT64)PsGetProcessDirectoryTableBase(e);   // undocumented export
#         o->eprocess = (UINT64)e;
#         ret = sizeof(AttachResult);
#         break;
#     }
#     case IOCTL_READ_VIRT: {
#         if (inLen < sizeof(ReadRequest)) return STATUS_BUFFER_TOO_SMALL;
#         ReadRequest *r = (ReadRequest *)inBuf;
#         // copy from the target into the same SystemBuffer, offset by the
#         // request header so one buffer serves both directions.
#         SIZE_T moved = MmCopyVirtualMemory(...);   // or a manual page-table walk
#         ret = (ULONG)moved;
#         break;
#     }
#     ...
#     }
#     Irp->IoStatus.Information = ret;
#     IoCompleteRequest(Irp, IO_NO_INCREMENT);
#     return STATUS_SUCCESS;
# }
