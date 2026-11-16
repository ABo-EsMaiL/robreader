#pragma once

#include <winuser.h>
#include <windows.h>

#include <cstdio>

/*
 * The upstream project pulled in the "crashlog" library to print a nice
 * stack trace when the game or the emulator crashes.  That library changed
 * its API and headers, and it is not needed for the emulator to work, so
 * this is now a plain handler that just shows a message.
 */
class exception_handler {
	static LONG WINAPI TopLevelExceptionFilter(struct _EXCEPTION_POINTERS *ExceptionInfo) {
		(void)ExceptionInfo;
		printf("[EAC emulator] unhandled exception\n");
		MessageBoxA(nullptr, "EAC emulator crashed", "Crashed!", MB_OK | MB_ICONERROR);
		return 0;
	}

   public:
	static void init() {
		SetUnhandledExceptionFilter(&TopLevelExceptionFilter);
	}
};
