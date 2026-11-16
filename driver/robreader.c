/*
 * robreader.c - a read-only kernel driver for reading another process's
 * virtual memory.
 *
 * Why this exists
 * ---------------
 * Easy Anti-Cheat registers a kernel callback that strips PROCESS_VM_READ
 * from every handle opened against the protected game, and it strips the
 * rights again when a handle is duplicated.  No user mode API can read the
 * game.  A driver can: MmCopyVirtualMemory with PreviousMode = KernelMode
 * copies straight out of the target's address space without going through
 * the object manager, so the anti-cheat callback never runs.
 *
 * Safety
 * ------
 * - READ ONLY.  There is no write path at all, so this driver cannot be
 *   used to patch the game.
 * - The target is addressed by PID and is looked up with
 *   PsLookupProcessByProcessId; the EPROCESS is only used as a source
 *   address space, never dereferenced by hand.
 * - The amount copied is bounded by the output buffer length.
 *
 * Interface
 * ---------
 *   device : \\.\RobReader
 *   ioctl  : IOCTL_ROB_READ
 *   input  : ROB_READ_REQUEST { ProcessId, Address, Size }
 *   output : the raw bytes that were read
 */

#include <ntddk.h>

#define ROB_DEVICE_NAME  L"\\Device\\RobReader"
#define ROB_DOS_DEVICE   L"\\DosDevices\\RobReader"
#define ROB_TAG          'borR'

#define IOCTL_ROB_READ   CTL_CODE(FILE_DEVICE_UNKNOWN, 0x800, METHOD_BUFFERED, FILE_ANY_ACCESS)

typedef struct _ROB_READ_REQUEST {
    ULONG ProcessId;
    ULONG Address;        /* low 32 bits of the target virtual address */
    ULONG64 Address64;    /* full 64 bit virtual address              */
    ULONG Size;           /* bytes to read                           */
    ULONG Reserved;
} ROB_READ_REQUEST;

typedef struct _ROB_READ_HEADER {
    NTSTATUS Status;
    ULONG BytesRead;
    ULONG64 Address;
} ROB_READ_HEADER;

DRIVER_OBJECT gDriverObject;

static void RobUnload(PDRIVER_OBJECT DriverObject)
{
    IoDeleteSymbolicLink((PUNICODE_STRING)ROB_DOS_DEVICE);
    if (DriverObject->DeviceObject)
        IoDeleteDevice(DriverObject->DeviceObject);
    DbgPrint("[RobReader] unloaded\n");
}

static NTSTATUS RobComplete(PIRP Irp, NTSTATUS Status, ULONG_PTR Info)
{
    Irp->IoStatus.Status = Status;
    Irp->IoStatus.Information = Info;
    IofCompleteRequest(Irp, IO_NO_INCREMENT);
    return Status;
}

static NTSTATUS RobDeviceControl(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PIO_STACK_LOCATION stack;
    PVOID systemBuffer;
    ULONG inLength, outLength;
    ROB_READ_REQUEST request;
    PEPROCESS process;
    NTSTATUS status;
    SIZE_T bytesRead = 0;
    PVOID address;

    UNREFERENCED_PARAMETER(DeviceObject);

    stack = IoGetCurrentIrpStackLocation(Irp);
    inLength = stack->Parameters.DeviceIoControl.InputBufferLength;
    outLength = stack->Parameters.DeviceIoControl.OutputBufferLength;
    systemBuffer = Irp->AssociatedIrp.SystemBuffer;

    if (inLength < sizeof(ROB_READ_REQUEST)) {
        return RobComplete(Irp, STATUS_BUFFER_TOO_SMALL, 0);
    }

    RtlCopyMemory(&request, systemBuffer, sizeof(ROB_READ_REQUEST));

    if (request.Size == 0 || request.Size > outLength) {
        return RobComplete(Irp, STATUS_INVALID_PARAMETER, 0);
    }

    status = PsLookupProcessByProcessId((HANDLE)(ULONG_PTR)request.ProcessId,
                                       &process);
    if (!NT_SUCCESS(status)) {
        return RobComplete(Irp, STATUS_INVALID_CID, 0);
    }

    address = (PVOID)(ULONG_PTR)request.Address64;

    /*
     * Copy from the target into our own address space.  PreviousMode =
     * KernelMode means the object manager is not consulted, so the anti
     * cheat's Ob callback does not get a chance to veto this.
     */
    status = MmCopyVirtualMemory(process,
                                 address,
                                 PsGetCurrentProcess(),
                                 systemBuffer,
                                 request.Size,
                                 KernelMode,
                                 &bytesRead);

    ObDereferenceObject(process);

    if (!NT_SUCCESS(status)) {
        return RobComplete(Irp, status, 0);
    }

    DbgPrint("[RobReader] pid %u addr %p -> %zu bytes\n",
             request.ProcessId, address, bytesRead);

    return RobComplete(Irp, STATUS_SUCCESS, (ULONG_PTR)bytesRead);
}

NTSTATUS DriverEntry(PDRIVER_OBJECT DriverObject,
                     PUNICODE_STRING RegistryPath)
{
    UNICODE_STRING deviceName;
    UNICODE_STRING dosName;
    PDEVICE_OBJECT deviceObject = NULL;
    NTSTATUS status;
    ULONG i;

    UNREFERENCED_PARAMETER(RegistryPath);

    for (i = 0; i < IRP_MJ_MAXIMUM_FUNCTION; i++)
        DriverObject->MajorFunction[i] = RobComplete;

    DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = RobDeviceControl;
    DriverObject->DriverUnload = RobUnload;
    gDriverObject = DriverObject;

    RtlInitUnicodeString(&deviceName, ROB_DEVICE_NAME);
    RtlInitUnicodeString(&dosName, ROB_DOS_DEVICE);

    status = IoCreateDevice(DriverObject,
                            0,
                            &deviceName,
                            FILE_DEVICE_UNKNOWN,
                            FILE_DEVICE_SECURE_OPEN,
                            FALSE,
                            &deviceObject);
    if (!NT_SUCCESS(status)) {
        DbgPrint("[RobReader] IoCreateDevice failed 0x%08X\n", status);
        return status;
    }

    status = IoCreateSymbolicLink(&dosName, &deviceName);
    if (!NT_SUCCESS(status)) {
        IoDeleteDevice(deviceObject);
        DbgPrint("[RobReader] IoCreateSymbolicLink failed 0x%08X\n", status);
        return status;
    }

    deviceObject->Flags |= DO_BUFFERED_IO;
    DbgPrint("[RobReader] loaded, device \\\\.\\RobReader\n");
    return STATUS_SUCCESS;
}
