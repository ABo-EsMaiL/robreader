/*
 * robbridge.c - kernel memory bridge for an external reader.
 *
 * Design notes
 * ------------
 * The driver is manual-mapped, so it must not assume it was loaded by the
 * service manager and it must not need any import other than ntoskrnl.
 * Everything below is plain WDM and plain C: no CRT, no SEH, no stack
 * cookie, no floating point.
 *
 * Reading another process is done by walking its page tables (CR3) and
 * mapping the resulting physical pages with MmMapIoSpace.  This avoids
 * KeStackAttachProcess entirely on the hot path, so no process attach is
 * visible and no handle is ever opened against the target.  The only kernel
 * API used to find the target is PsLookupProcessByProcessId.
 *
 * Two hard rules learned the expensive way (two 0x50 bugchecks):
 *
 *  1. A present PTE does not mean the page is RAM.  GPU / device mappings
 *     point at MMIO ranges, and both MmMapIoSpace and MmCopyMemory(PHYSICAL)
 *     bugcheck when handed one.  Every physical address is therefore checked
 *     against MmGetPhysicalMemoryRanges() before it is touched.
 *  2. MmCopyVirtualMemory is not a bulk-copy primitive for a kernel buffer:
 *     it over-copies by the source page offset and writes past the caller's
 *     buffer.  It is not used at all any more.
 *
 * Windows 11 build 26200 refuses to map page-table pages with MmMapIoSpace
 * (it returns NULL, while neighbouring data pages map fine), so the walk
 * reads PTEs with MmCopyMemory(MM_COPY_MEMORY_PHYSICAL).
 *
 * The scan-safe path (IOCTL_RBX_SREAD) does attach, then copies with
 * MmCopyMemory(MM_COPY_MEMORY_VIRTUAL) -- the same primitive crash-dump
 * writers use, which resolves every page kind (including device memory)
 * without ever naming a physical address.
 *
 * KPROCESS.DirectoryTableBase is at offset 0x28 on every x64 Windows since
 * Windows 7, so the CR3 offset is not guessed from a build number.
 *
 * Interface (all METHOD_BUFFERED, no symbolic link):
 *
 *   \\?\GLOBALROOT\Device\Rbt
 *
 *   IOCTL_RBX_PING    - no input,  RBX_PING_RESP out
 *   IOCTL_RBX_INFO    - RBX_INFO_REQ in (pid), RBX_INFO_RESP out
 *   IOCTL_RBX_READ    - RBX_MEM_REQ in, raw bytes out
 *   IOCTL_RBX_SREAD   - same, forced through attach + MmCopyMemory(VIRTUAL)
 *   IOCTL_RBX_WRITE   - RBX_MEM_REQ + payload in
 *   IOCTL_RBX_KREAD   - RBX_KREQ in, raw bytes out       (kernel VA)
 *   IOCTL_RBX_KWRITE  - RBX_KREQ + payload in            (kernel VA)
 *   IOCTL_RBX_VA2PA   - RBX_MEM_REQ in, ULONG64 pa out
 */

#include <ntifs.h>

#define RBX_DEVICE_DEFAULT  L"\\Device\\Rbt"

/*
 * Writable on purpose: the mapper rewrites this buffer in the image before it
 * is copied into the kernel.  Manual mapping has no unload path, so a second
 * map has to pick a different name instead of colliding with the first one.
 * The buffer is 64 wide chars; the mapper zero-fills the remainder.
 */
static WCHAR g_DeviceName[64] = RBX_DEVICE_DEFAULT;

#define RBX_MAGIC           0x47425852UL   /* 'RBXG' */
#define RBX_VERSION         4UL

/* which copy path the last IOCTL_RBX_READ/WRITE used */
#define RBX_PATH_NONE       0UL
#define RBX_PATH_CR3        1UL
#define RBX_PATH_API        2UL

#define IOCTL_RBX_PING    CTL_CODE(FILE_DEVICE_UNKNOWN, 0x800, METHOD_BUFFERED, FILE_ANY_ACCESS)
#define IOCTL_RBX_INFO    CTL_CODE(FILE_DEVICE_UNKNOWN, 0x801, METHOD_BUFFERED, FILE_ANY_ACCESS)
#define IOCTL_RBX_READ    CTL_CODE(FILE_DEVICE_UNKNOWN, 0x802, METHOD_BUFFERED, FILE_ANY_ACCESS)
#define IOCTL_RBX_WRITE   CTL_CODE(FILE_DEVICE_UNKNOWN, 0x803, METHOD_BUFFERED, FILE_ANY_ACCESS)
#define IOCTL_RBX_KREAD   CTL_CODE(FILE_DEVICE_UNKNOWN, 0x804, METHOD_BUFFERED, FILE_ANY_ACCESS)
#define IOCTL_RBX_KWRITE  CTL_CODE(FILE_DEVICE_UNKNOWN, 0x805, METHOD_BUFFERED, FILE_ANY_ACCESS)
#define IOCTL_RBX_VA2PA   CTL_CODE(FILE_DEVICE_UNKNOWN, 0x806, METHOD_BUFFERED, FILE_ANY_ACCESS)
/* same request as IOCTL_RBX_READ but forced through attach +
 * MmCopyMemory(VIRTUAL): the memory manager resolves every page kind,
 * including device/GPU mappings, and no physical address is ever used. */
#define IOCTL_RBX_SREAD   CTL_CODE(FILE_DEVICE_UNKNOWN, 0x807, METHOD_BUFFERED, FILE_ANY_ACCESS)

typedef struct _RBX_MEM_REQ {
    ULONG   ProcessId;
    ULONG   Size;
    ULONG64 Address;
} RBX_MEM_REQ;

typedef struct _RBX_KREQ {
    ULONG64 Address;
    ULONG   Size;
    ULONG   Reserved;
} RBX_KREQ;

typedef struct _RBX_INFO_REQ {
    ULONG   ProcessId;
    ULONG   Reserved;
} RBX_INFO_REQ;

typedef struct _RBX_INFO_RESP {
    ULONG64 Cr3;
    ULONG64 Peb;
    ULONG   ProcessId;
    ULONG   Reserved;
} RBX_INFO_RESP;

typedef struct _RBX_PING_RESP {
    ULONG   Magic;
    ULONG   Version;
    ULONG64 ImageBase;
    ULONG64 Unused;
} RBX_PING_RESP;

/* ------------------------------------------------------------------ */
/* minimal helpers (memcpy/memset are intrinsics in kernel headers)    */
/* ------------------------------------------------------------------ */

void *RbxCopy(void *dst, const void *src, size_t len)
{
    unsigned char *d = (unsigned char *)dst;
    const unsigned char *s = (const unsigned char *)src;

    while (len--)
        *d++ = *s++;
    return dst;
}

void *RbxZero(void *dst, size_t len)
{
    unsigned char *d = (unsigned char *)dst;

    while (len--)
        *d++ = 0;
    return dst;
}

/* Not declared by every WDK header; the linker still finds it in ntoskrnl. */
struct _RBX_PEB;
struct _RBX_PEB *PsGetProcessPeb(PEPROCESS Process);

/* ------------------------------------------------------------------ */
/* physical page cache                                                 */
/* ------------------------------------------------------------------ */

#define RBX_PAGE_SIZE   0x1000UL
#define RBX_CACHE_SLOTS 16

#define RBX_PTE_PRESENT 0x0000000000000001ULL
#define RBX_PTE_LARGE   0x0000000000000080ULL
#define RBX_PHYS_MASK   0x000FFFFFFFFFF000ULL
#define RBX_PHYS_1G     0x000FFFFFC0000000ULL
#define RBX_PHYS_2M     0x000FFFFFFFE00000ULL

typedef struct _RBX_SLOT {
    ULONG64 Phys;
    PVOID   Va;
    ULONG64 Stamp;
} RBX_SLOT;

static RBX_SLOT g_Slots[RBX_CACHE_SLOTS];
static ULONG64  g_Stamp;
static ULONG64  g_ImageBase;
static ULONG    g_LastPath = RBX_PATH_NONE;

/* ------------------------------------------------------------------ */
/* RAM map guard                                                       */
/* ------------------------------------------------------------------ */

/*
 * A present PTE can point at MMIO (GPU, device BARs).  Handing such an
 * address to MmMapIoSpace or MmCopyMemory(PHYSICAL) bugchecks 0x50 inside
 * memmove.  Every physical address we are about to touch is checked against
 * the real RAM ranges first.
 */
#define RBX_MAX_RAM_RANGES 96

static ULONG64 g_RamBase[RBX_MAX_RAM_RANGES];
static ULONG64 g_RamEnd[RBX_MAX_RAM_RANGES];
static ULONG   g_RamCount;

static VOID RbxLoadRamRanges(VOID)
{
    PPHYSICAL_MEMORY_RANGE ranges;
    ULONG i;

    g_RamCount = 0;
    ranges = MmGetPhysicalMemoryRanges();
    if (ranges == NULL)
        return;

    for (i = 0; i < RBX_MAX_RAM_RANGES; i++) {
        LONGLONG bytes = ranges[i].NumberOfBytes.QuadPart;

        if (bytes == 0)
            break;
        g_RamBase[i] = (ULONG64)ranges[i].BaseAddress.QuadPart;
        g_RamEnd[i] = g_RamBase[i] + (ULONG64)bytes;
    }
    g_RamCount = i;
    ExFreePool(ranges);
}

static BOOLEAN RbxPhysIsRam(ULONG64 Phys)
{
    ULONG i;

    if (g_RamCount == 0)
        return FALSE;

    for (i = 0; i < g_RamCount; i++) {
        if (Phys >= g_RamBase[i] && Phys < g_RamEnd[i])
            return TRUE;
    }
    return FALSE;
}


static PVOID RbxMapPage(ULONG64 Phys)
{
    ULONG i;
    ULONG victim = RBX_CACHE_SLOTS;
    ULONG64 oldest = ~(ULONG64)0;
    PHYSICAL_ADDRESS pa;

    Phys &= RBX_PHYS_MASK;
    if (Phys == 0)
        return NULL;

    if (!RbxPhysIsRam(Phys))
        return NULL;

    for (i = 0; i < RBX_CACHE_SLOTS; i++) {
        if (g_Slots[i].Va != NULL && g_Slots[i].Phys == Phys) {
            g_Slots[i].Stamp = ++g_Stamp;
            return g_Slots[i].Va;
        }
    }

    for (i = 0; i < RBX_CACHE_SLOTS; i++) {
        if (g_Slots[i].Va == NULL) {
            victim = i;
            break;
        }
        if (g_Slots[i].Stamp < oldest) {
            oldest = g_Slots[i].Stamp;
            victim = i;
        }
    }

    if (victim == RBX_CACHE_SLOTS)
        return NULL;

    if (g_Slots[victim].Va != NULL) {
        MmUnmapIoSpace(g_Slots[victim].Va, RBX_PAGE_SIZE);
        g_Slots[victim].Va = NULL;
    }

    pa.QuadPart = (LONGLONG)Phys;
    g_Slots[victim].Va = MmMapIoSpace(pa, RBX_PAGE_SIZE, MmCached);
    g_Slots[victim].Phys = Phys;
    g_Slots[victim].Stamp = ++g_Stamp;
    return g_Slots[victim].Va;
}

static BOOLEAN RbxReadPhysQword(ULONG64 Phys, ULONG64 *Value)
{
    MM_COPY_ADDRESS source;
    SIZE_T transferred = 0;
    NTSTATUS status;
    PUCHAR page;

    if (!RbxPhysIsRam(Phys & ~7ULL))
        return FALSE;

    /*
     * Page-table pages cannot be mapped with MmMapIoSpace on recent builds,
     * but MmCopyMemory reads them straight out of physical memory.
     */
    source.PhysicalAddress.QuadPart = (LONGLONG)(Phys & ~7ULL);
    status = MmCopyMemory(Value, source, sizeof(*Value),
                          MM_COPY_MEMORY_PHYSICAL, &transferred);
    if (NT_SUCCESS(status) && transferred == sizeof(*Value))
        return TRUE;

    page = (PUCHAR)RbxMapPage(Phys);
    if (page == NULL)
        return FALSE;
    *Value = *(ULONG64 *)(page + (ULONG)(Phys & 0xFFF));
    return TRUE;
}

static BOOLEAN RbxTranslate(ULONG64 Cr3, ULONG64 Va, ULONG64 *Pa)
{
    ULONG64 e;
    ULONG64 table;

    table = Cr3 & RBX_PHYS_MASK;
    if (table == 0)
        return FALSE;

    if (!RbxReadPhysQword(table + ((Va >> 39) & 0x1FF) * 8, &e))
        return FALSE;
    if (!(e & RBX_PTE_PRESENT))
        return FALSE;
    table = e & RBX_PHYS_MASK;
    if (table == 0)
        return FALSE;

    if (!RbxReadPhysQword(table + ((Va >> 30) & 0x1FF) * 8, &e))
        return FALSE;
    if (!(e & RBX_PTE_PRESENT))
        return FALSE;
    if (e & RBX_PTE_LARGE) {
        *Pa = (e & RBX_PHYS_1G) + (Va & 0x3FFFFFFFULL);
        return TRUE;
    }
    table = e & RBX_PHYS_MASK;
    if (table == 0)
        return FALSE;

    if (!RbxReadPhysQword(table + ((Va >> 21) & 0x1FF) * 8, &e))
        return FALSE;
    if (!(e & RBX_PTE_PRESENT))
        return FALSE;
    if (e & RBX_PTE_LARGE) {
        *Pa = (e & RBX_PHYS_2M) + (Va & 0x1FFFFFULL);
        return TRUE;
    }
    table = e & RBX_PHYS_MASK;
    if (table == 0)
        return FALSE;

    if (!RbxReadPhysQword(table + ((Va >> 12) & 0x1FF) * 8, &e))
        return FALSE;
    if (!(e & RBX_PTE_PRESENT))
        return FALSE;

    *Pa = (e & RBX_PHYS_MASK) + (Va & 0xFFF);
    return TRUE;
}

/* ------------------------------------------------------------------ */
/* process copy                                                        */
/* ------------------------------------------------------------------ */

static NTSTATUS RbxCopyProcessCr3(ULONG ProcessId, ULONG64 Address,
                                  PVOID Buffer, ULONG Size, BOOLEAN Write)
{
    PEPROCESS process = NULL;
    NTSTATUS status;
    ULONG64 cr3;
    PUCHAR buf = (PUCHAR)Buffer;
    ULONG left = Size;

    status = PsLookupProcessByProcessId((HANDLE)(ULONG_PTR)ProcessId, &process);
    if (!NT_SUCCESS(status))
        return status;

    cr3 = *(ULONG64 *)((PUCHAR)process + 0x28);
    ObDereferenceObject(process);

    if (cr3 == 0)
        return STATUS_NOT_FOUND;

    status = STATUS_SUCCESS;

    while (left > 0) {
        ULONG64 pa;
        ULONG offset;
        ULONG chunk;
        PUCHAR page;

        if (!RbxTranslate(cr3, Address, &pa)) {
            status = STATUS_PARTIAL_COPY;
            break;
        }

        offset = (ULONG)(pa & 0xFFF);
        chunk = RBX_PAGE_SIZE - offset;
        if (chunk > left)
            chunk = left;

        page = (PUCHAR)RbxMapPage(pa & ~((ULONG64)RBX_PAGE_SIZE - 1));
        if (page == NULL) {
            status = STATUS_INSUFFICIENT_RESOURCES;
            break;
        }

        if (Write)
            RbxCopy(page + offset, buf, chunk);
        else
            RbxCopy(buf, page + offset, chunk);

        Address += chunk;
        buf += chunk;
        left -= chunk;
    }

    return status;
}

/*
 * Scan-safe path.  There is still no handle and no OpenProcess: the source
 * process comes from PsLookupProcessByProcessId.  We attach, then copy with
 * MmCopyMemory(MM_COPY_MEMORY_VIRTUAL) so the memory manager resolves each
 * page itself (device/GPU pages included) and no physical address is ever
 * dereferenced by us.
 */
static NTSTATUS RbxCopyVirtual(ULONG ProcessId, ULONG64 Address, PVOID Buffer,
                               ULONG Size)
{
    PEPROCESS source = NULL;
    KAPC_STATE apc;
    MM_COPY_ADDRESS src;
    NTSTATUS status;
    SIZE_T done = 0;

    status = PsLookupProcessByProcessId((HANDLE)(ULONG_PTR)ProcessId, &source);
    if (!NT_SUCCESS(status))
        return status;

    src.VirtualAddress = (PVOID)(ULONG_PTR)Address;

    KeStackAttachProcess(source, &apc);
    status = MmCopyMemory(Buffer, src, Size, MM_COPY_MEMORY_VIRTUAL, &done);
    KeUnstackDetachProcess(&apc);

    ObDereferenceObject(source);

    if (!NT_SUCCESS(status))
        return status;
    if (done != Size)
        return STATUS_PARTIAL_COPY;
    return STATUS_SUCCESS;
}

static NTSTATUS RbxCopyProcess(ULONG ProcessId, ULONG64 Address,
                               PVOID Buffer, ULONG Size, BOOLEAN Write)
{
    NTSTATUS status;

    if (Write) {
        /* a write needs a writable mapping of the physical page; the RAM
         * guard inside the CR3 path is what keeps that legal */
        g_LastPath = RBX_PATH_CR3;
        return RbxCopyProcessCr3(ProcessId, Address, Buffer, Size, TRUE);
    }

    status = RbxCopyProcessCr3(ProcessId, Address, Buffer, Size, FALSE);
    if (NT_SUCCESS(status)) {
        g_LastPath = RBX_PATH_CR3;
        return status;
    }

    g_LastPath = RBX_PATH_API;
    return RbxCopyVirtual(ProcessId, Address, Buffer, Size);
}

static BOOLEAN RbxRangeValid(ULONG64 Address, ULONG Size)
{
    ULONG64 cur = Address;
    ULONG64 end = Address + Size;

    if (end < Address)
        return FALSE;

    while (cur < end) {
        if (!MmIsAddressValid((PVOID)(ULONG_PTR)cur))
            return FALSE;
        cur = (cur & ~0xFFFULL) + RBX_PAGE_SIZE;
    }
    return TRUE;
}

/* ------------------------------------------------------------------ */
/* IRP plumbing                                                        */
/* ------------------------------------------------------------------ */

static NTSTATUS RbxComplete(PIRP Irp, NTSTATUS Status, ULONG_PTR Information)
{
    Irp->IoStatus.Status = Status;
    Irp->IoStatus.Information = Information;
    IofCompleteRequest(Irp, IO_NO_INCREMENT);
    return Status;
}

static NTSTATUS RbxUnsupported(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    return RbxComplete(Irp, STATUS_INVALID_DEVICE_REQUEST, 0);
}

static NTSTATUS RbxCreateClose(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    return RbxComplete(Irp, STATUS_SUCCESS, 0);
}

static NTSTATUS RbxDeviceControl(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PIO_STACK_LOCATION stack;
    PVOID buffer;
    ULONG inLength;
    ULONG outLength;
    ULONG code;
    NTSTATUS status = STATUS_INVALID_DEVICE_REQUEST;
    ULONG_PTR information = 0;

    UNREFERENCED_PARAMETER(DeviceObject);

    stack = IoGetCurrentIrpStackLocation(Irp);
    code = stack->Parameters.DeviceIoControl.IoControlCode;
    inLength = stack->Parameters.DeviceIoControl.InputBufferLength;
    outLength = stack->Parameters.DeviceIoControl.OutputBufferLength;
    buffer = Irp->AssociatedIrp.SystemBuffer;

    if (buffer == NULL && (inLength != 0 || outLength != 0))
        return RbxComplete(Irp, STATUS_INVALID_PARAMETER, 0);

    switch (code) {

    case IOCTL_RBX_PING: {
        RBX_PING_RESP *resp = (RBX_PING_RESP *)buffer;

        if (outLength < sizeof(RBX_PING_RESP)) {
            status = STATUS_BUFFER_TOO_SMALL;
            break;
        }
        resp->Magic = RBX_MAGIC;
        resp->Version = RBX_VERSION;
        resp->ImageBase = g_ImageBase;
        resp->Unused = g_LastPath;
        information = sizeof(RBX_PING_RESP);
        status = STATUS_SUCCESS;
        break;
    }

    case IOCTL_RBX_INFO: {
        RBX_INFO_REQ request;
        RBX_INFO_RESP *resp = (RBX_INFO_RESP *)buffer;
        PEPROCESS process = NULL;

        if (inLength < sizeof(request) || outLength < sizeof(RBX_INFO_RESP)) {
            status = STATUS_BUFFER_TOO_SMALL;
            break;
        }
        RbxCopy(&request, buffer, sizeof(request));

        status = PsLookupProcessByProcessId((HANDLE)(ULONG_PTR)request.ProcessId,
                                            &process);
        if (!NT_SUCCESS(status))
            break;

        resp->Cr3 = *(ULONG64 *)((PUCHAR)process + 0x28);
        resp->Peb = (ULONG64)(ULONG_PTR)PsGetProcessPeb(process);
        resp->ProcessId = request.ProcessId;
        resp->Reserved = 0;
        ObDereferenceObject(process);
        information = sizeof(RBX_INFO_RESP);
        status = STATUS_SUCCESS;
        break;
    }

    case IOCTL_RBX_READ: {
        RBX_MEM_REQ request;

        if (inLength < sizeof(request)) {
            status = STATUS_BUFFER_TOO_SMALL;
            break;
        }
        RbxCopy(&request, buffer, sizeof(request));

        if (request.Size == 0 || request.Size > outLength) {
            status = STATUS_INVALID_PARAMETER;
            break;
        }

        status = RbxCopyProcess(request.ProcessId, request.Address,
                                buffer, request.Size, FALSE);
        if (NT_SUCCESS(status))
            information = request.Size;
        break;
    }

    case IOCTL_RBX_SREAD: {
        RBX_MEM_REQ request;

        if (inLength < sizeof(request)) {
            status = STATUS_BUFFER_TOO_SMALL;
            break;
        }
        RbxCopy(&request, buffer, sizeof(request));

        if (request.Size == 0 || request.Size > outLength) {
            status = STATUS_INVALID_PARAMETER;
            break;
        }

        status = RbxCopyVirtual(request.ProcessId, request.Address,
                                buffer, request.Size);
        if (NT_SUCCESS(status))
            information = request.Size;
        break;
    }

    case IOCTL_RBX_WRITE: {
        RBX_MEM_REQ request;

        if (inLength < sizeof(request)) {
            status = STATUS_BUFFER_TOO_SMALL;
            break;
        }
        RbxCopy(&request, buffer, sizeof(request));

        if (request.Size == 0 || request.Size > inLength - sizeof(request)) {
            status = STATUS_INVALID_PARAMETER;
            break;
        }

        status = RbxCopyProcess(request.ProcessId, request.Address,
                                (PUCHAR)buffer + sizeof(request),
                                request.Size, TRUE);
        if (NT_SUCCESS(status))
            information = request.Size;
        break;
    }

    case IOCTL_RBX_KREAD: {
        RBX_KREQ request;

        if (inLength < sizeof(request)) {
            status = STATUS_BUFFER_TOO_SMALL;
            break;
        }
        RbxCopy(&request, buffer, sizeof(request));

        if (request.Size == 0 || request.Size > outLength) {
            status = STATUS_INVALID_PARAMETER;
            break;
        }
        if (!RbxRangeValid(request.Address, request.Size)) {
            status = STATUS_INVALID_ADDRESS;
            break;
        }

        RbxCopy(buffer, (PVOID)(ULONG_PTR)request.Address, request.Size);
        information = request.Size;
        status = STATUS_SUCCESS;
        break;
    }

    case IOCTL_RBX_KWRITE: {
        RBX_KREQ request;

        if (inLength < sizeof(request)) {
            status = STATUS_BUFFER_TOO_SMALL;
            break;
        }
        RbxCopy(&request, buffer, sizeof(request));

        if (request.Size == 0 || request.Size > inLength - sizeof(request)) {
            status = STATUS_INVALID_PARAMETER;
            break;
        }
        if (!RbxRangeValid(request.Address, request.Size)) {
            status = STATUS_INVALID_ADDRESS;
            break;
        }

        RbxCopy((PVOID)(ULONG_PTR)request.Address,
               (PUCHAR)buffer + sizeof(request), request.Size);
        information = request.Size;
        status = STATUS_SUCCESS;
        break;
    }

    case IOCTL_RBX_VA2PA: {
        RBX_MEM_REQ request;
        ULONG64 *out = (ULONG64 *)buffer;
        PEPROCESS process = NULL;
        ULONG64 cr3;
        ULONG64 pa;

        if (inLength < sizeof(request) || outLength < sizeof(ULONG64)) {
            status = STATUS_BUFFER_TOO_SMALL;
            break;
        }
        RbxCopy(&request, buffer, sizeof(request));

        status = PsLookupProcessByProcessId((HANDLE)(ULONG_PTR)request.ProcessId,
                                            &process);
        if (!NT_SUCCESS(status))
            break;

        cr3 = *(ULONG64 *)((PUCHAR)process + 0x28);
        ObDereferenceObject(process);

        if (!RbxTranslate(cr3, request.Address, &pa)) {
            status = STATUS_NOT_FOUND;
            break;
        }
        *out = pa;
        information = sizeof(ULONG64);
        status = STATUS_SUCCESS;
        break;
    }

    default:
        status = STATUS_INVALID_DEVICE_REQUEST;
        break;
    }

    return RbxComplete(Irp, status, information);
}

/* ------------------------------------------------------------------ */
/* entry                                                               */
/* ------------------------------------------------------------------ */

NTSTATUS DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    UNICODE_STRING deviceName;
    PDEVICE_OBJECT deviceObject = NULL;
    NTSTATUS status;
    ULONG i;

    UNREFERENCED_PARAMETER(RegistryPath);

    /*
     * Manual mapping passes the driver object supplied by IoCreateDriver.
     * A NULL here means somebody tried to run the mapped image as an entry
     * point directly; refuse instead of faulting.
     */
    if (DriverObject == NULL)
        return STATUS_INVALID_PARAMETER;

    g_ImageBase = 0;
    g_Stamp = 0;

    RbxLoadRamRanges();

    for (i = 0; i <= IRP_MJ_MAXIMUM_FUNCTION; i++)
        DriverObject->MajorFunction[i] = RbxUnsupported;

    DriverObject->MajorFunction[IRP_MJ_CREATE] = RbxCreateClose;
    DriverObject->MajorFunction[IRP_MJ_CLOSE] = RbxCreateClose;
    DriverObject->MajorFunction[IRP_MJ_CLEANUP] = RbxCreateClose;
    DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = RbxDeviceControl;
    DriverObject->DriverUnload = NULL;

    RtlInitUnicodeString(&deviceName, g_DeviceName);

    status = IoCreateDevice(DriverObject,
                            0,
                            &deviceName,
                            FILE_DEVICE_UNKNOWN,
                            FILE_DEVICE_SECURE_OPEN,
                            FALSE,
                            &deviceObject);
    if (!NT_SUCCESS(status))
        return status;

    deviceObject->Flags |= DO_BUFFERED_IO;

    /*
     * IoCreateDevice sets DO_DEVICE_INITIALIZING and the I/O manager clears it
     * after DriverEntry returns -- but only when the service manager loaded
     * the image.  A manually mapped driver gets no such help, and every open
     * of the device would fail with STATUS_NO_SUCH_DEVICE.
     */
    deviceObject->Flags &= ~DO_DEVICE_INITIALIZING;

    return STATUS_SUCCESS;
}
