"""
win.py - Minimal Win32 bindings used by the user-mode memory API.

Only what we actually need:
  * CreateFileW / DeviceIoControl / CloseHandle  -> talk to a kernel driver
  * VirtualQueryEx / Toolhelp snapshot            -> module enumeration

Everything is ctypes; no third-party dependencies. Python 3.9+.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from typing import List, Optional

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

# NtQuerySystemInformation information classes
SystemExtendedHandleInformation = 64

# ---------------------------------------------------------------- constants
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
TH32CS_SNAPPROCESS = 0x00000002

PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_FREE = 0x10000

# ---------------------------------------------------------------- structures
class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256),
        ("szExePath", wintypes.WCHAR * 260),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


# ---------------------------------------------------------------- prototypes
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE

kernel32.DeviceIoControl.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]
kernel32.DeviceIoControl.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.VirtualQueryEx.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t,
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t

kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

kernel32.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32FirstW.restype = wintypes.BOOL

kernel32.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32NextW.restype = wintypes.BOOL

kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL

kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL

try:
    psapi = ctypes.WinDLL("psapi")
except OSError:  # pragma: no cover
    psapi = None

if psapi is not None:
    class MODULEINFO(ctypes.Structure):
        _fields_ = [("lpBaseOfDll", ctypes.c_void_p),
                    ("SizeOfImage", ctypes.c_ulong),
                    ("EntryPoint", ctypes.c_void_p)]

    LIST_MODULES_ALL = 0x03
    psapi.EnumProcessModulesEx.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
    ]
    psapi.EnumProcessModulesEx.restype = wintypes.BOOL
    psapi.GetModuleBaseNameW.argtypes = [
        wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD,
    ]
    psapi.GetModuleBaseNameW.restype = wintypes.DWORD
    psapi.GetModuleInformation.argtypes = [
        wintypes.HANDLE, wintypes.HMODULE,
        ctypes.POINTER(MODULEINFO), wintypes.DWORD,
    ]
    psapi.GetModuleInformation.restype = wintypes.BOOL


def list_modules_by_handle(handle, name_filter: str = ""):
    """Enumerate the modules of a process we hold a handle to.

    Works for other processes (unlike Toolhelp snapshots) as long as the
    handle carries PROCESS_QUERY_INFORMATION | PROCESS_VM_READ.
    Returns [(base, size, name)].
    """
    if psapi is None:
        raise OSError("psapi is unavailable")
    count = 1024
    mods = (wintypes.HMODULE * count)()
    needed = wintypes.DWORD(0)
    if not psapi.EnumProcessModulesEx(handle, mods, ctypes.sizeof(mods),
                                     ctypes.byref(needed), LIST_MODULES_ALL):
        raise OSError(f"EnumProcessModulesEx failed: {GetLastError()}")
    n = needed.value // ctypes.sizeof(wintypes.HMODULE)
    out = []
    for i in range(min(n, count)):
        m = mods[i]
        buf = ctypes.create_unicode_buffer(260)
        if not psapi.GetModuleBaseNameW(handle, m, buf, 260):
            continue
        mod_name = buf.value
        if name_filter and mod_name.lower() != name_filter.lower():
            continue
        mi = MODULEINFO()
        if not psapi.GetModuleInformation(handle, m, ctypes.byref(mi),
                                         ctypes.sizeof(mi)):
            continue
        out.append((int(mi.lpBaseOfDll or 0), int(mi.SizeOfImage), mod_name))
    return out

kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.WriteProcessMemory.restype = wintypes.BOOL

kernel32.VirtualQueryEx.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t,
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t


# ---------------------------------------------------------------- helpers
def winerror() -> int:
    return ctypes.get_last_error()


def open_device(path: str, access: int = GENERIC_READ | GENERIC_WRITE) -> int:
    """Open a kernel device object (e.g. r'\\\\.\\MyDriver')."""
    handle = kernel32.CreateFileW(
        path, access, FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
    )
    if handle == INVALID_HANDLE_VALUE or handle is None:
        raise OSError(winerror(), f"CreateFileW({path!r}) failed")
    return handle


def close_handle(handle: int) -> None:
    if handle and handle != INVALID_HANDLE_VALUE:
        kernel32.CloseHandle(handle)


def device_io_control(handle: int, code: int, in_buf, in_len: int, out_buf, out_len: int) -> int:
    """Returns the number of bytes written into out_buf."""
    returned = wintypes.DWORD(0)
    ok = kernel32.DeviceIoControl(
        handle, code,
        ctypes.byref(in_buf) if in_buf is not None else None, in_len,
        ctypes.byref(out_buf) if out_buf is not None else None, out_len,
        ctypes.byref(returned), None,
    )
    if not ok:
        raise OSError(winerror(), f"DeviceIoControl(0x{code:08X}) failed")
    return returned.value


def find_pid(exe_name: str) -> Optional[int]:
    """Find a running process by executable name (case-insensitive)."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() == exe_name.lower():
                    return int(entry.th32ProcessID)
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        close_handle(snap)
    return None


def list_modules(pid: int) -> List[tuple]:
    """Return [(base, size, name)] for a process. Needs PROCESS_QUERY_INFORMATION."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE_VALUE:
        return []
    out = []
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if kernel32.Module32FirstW(snap, ctypes.byref(entry)):
            while True:
                base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                out.append((base, int(entry.modBaseSize), entry.szModule))
                if not kernel32.Module32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        close_handle(snap)
    return out


def protection_name(protect: int) -> str:
    base = protect & 0xFF
    names = {
        PAGE_NOACCESS: "NOACCESS", PAGE_READONLY: "R", PAGE_READWRITE: "RW",
        PAGE_WRITECOPY: "WC", PAGE_EXECUTE: "X", PAGE_EXECUTE_READ: "RX",
        PAGE_EXECUTE_READWRITE: "RWX",
    }
    return names.get(base, hex(base))
