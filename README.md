# robreader - a read-only kernel driver for reading protected processes

Easy Anti-Cheat installs a kernel callback that strips `PROCESS_VM_READ` from
every handle opened against the game, and strips it again when a handle is
duplicated.  That is why `ReadProcessMemory`, handle stealing and every other
user mode trick fail against an EAC protected game.

A driver can still read it: `MmCopyVirtualMemory` with
`PreviousMode = KernelMode` copies straight out of the target's address space
without consulting the object manager, so the anti-cheat callback never runs.

This repository contains a **read only** driver that does exactly that and
nothing else.  There is no write path, so the driver cannot be used to patch
the game.

## What is in here

```
driver/robreader.c      the driver (WDM, plain C)
.github/workflows/      builds it with the Windows Driver Kit
```

## The interface

```
device : \\.\RobReader
ioctl  : IOCTL_ROB_READ = 0x22002000
input  : struct { ULONG ProcessId; ULONG Address; ULONG64 Address64;
                  ULONG Size; ULONG Reserved; }
output : the raw bytes that were read
```

The request and the reply share one buffer (METHOD_BUFFERED): the request
occupies the first 24 bytes and the data follows it.  The driver copies the
request out before writing the data, so the reply starts at offset 0.

## Build

Push the repository to GitHub and the workflow
`.github/workflows/build-robreader.yml` builds it on the `windows-2022`
runner, which ships the Windows Driver Kit.

Artifacts:

| file | what it is |
|---|---|
| `robreader-signed.sys` | the driver, signed with a throw away certificate |
| `robreader-cert.cer` | that certificate, install it in Trusted Root |
| `robreader.zip` | both of the above |

To build it by hand on a Windows machine with the WDK installed:

```
cl /kernel /c /Zl /Wv /GS- /GR- /EHs- /std:c17 /D_KERNEL_MODE /D_UNICODE ^
   /D_AMD64_ /D_AMD64 /D_X86_64 driver\robreader.c
link /driver /subsystem:native /entry:DriverEntry /machine:x64 /nodefaultlib ^
   /out:robreader.sys robreader.obj /lib:ntoskrnl.lib /lib:hal.lib ^
   /lib:wmip.lib /lib:ndis.lib
```

## Install

The driver is signed with a self signed certificate, so Windows only loads
it in **test signing mode**:

```
bcdedit /set testsigning on
< reboot >
```

then, from an elevated shell:

```
certutil -addstore -f Root robreader-cert.cer
copy robreader-signed.sys C:\Windows\System32\drivers\robreader.sys
sc create robreader type= kernel start= demand binPath= C:\Windows\System32\drivers\robreader.sys
sc start robreader
```

Test signing lowers the bar for unsigned kernel code, which is why it is a
developer mode only setting.  Turn it off again with
`bcdedit /set testsigning off` plus a reboot when you are done.

## Use

```c
/* from user mode, after opening \\.\RobReader */
DeviceIoControl(h, 0x22002000, request, 24, buffer, size, &returned, NULL);
```
