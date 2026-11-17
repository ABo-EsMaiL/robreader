#pragma once

#include <winuser.h>
#include <windows.h>

#include <cstdio>
#include <cstring>

/*
 * The upstream project pulled in the "crashlog" library to print a nice
 * stack trace when the game or the emulator crashes.  That library changed
 * its API and headers, and it is not needed for the emulator to work, so
 * this is now a plain handler that records the exception details and shows
 * a message box.  The details are written to eac-exception.log next to the
 * game executable so a popup alone is never the only clue.
 */
class exception_handler {
	static LONG WINAPI TopLevelExceptionFilter(struct _EXCEPTION_POINTERS* ExceptionInfo) {
		DWORD code = 0;
		PVOID address = nullptr;
		if (ExceptionInfo != nullptr && ExceptionInfo->ExceptionRecord != nullptr) {
			code = ExceptionInfo->ExceptionRecord->ExceptionCode;
			address = ExceptionInfo->ExceptionRecord->ExceptionAddress;
		}

		char module_path[MAX_PATH] = {0};
		const char* module_name = "<unknown>";
		unsigned long long module_offset = 0;
		HMODULE module = nullptr;
		if (address != nullptr &&
			GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
			                   reinterpret_cast<LPCSTR>(address), &module) &&
			module != nullptr) {
			DWORD length = GetModuleFileNameA(module, module_path, MAX_PATH);
			if (length > 0) {
				char* separator = std::strrchr(module_path, '\\');
				module_name = separator != nullptr ? separator + 1 : module_path;
			}
			module_offset = static_cast<unsigned long long>(
				reinterpret_cast<unsigned char*>(address) - reinterpret_cast<unsigned char*>(module));
		}

		/* Put the log beside the game executable (the DLL cannot rely on the
		 * process working directory being the game folder). */
		char exe_path[MAX_PATH] = {0};
		GetModuleFileNameA(nullptr, exe_path, MAX_PATH);
		char* exe_separator = std::strrchr(exe_path, '\\');
		if (exe_separator != nullptr) {
			*(exe_separator + 1) = '\0';
		} else {
			exe_path[0] = '\0';
		}
		char log_path[MAX_PATH] = {0};
		std::snprintf(log_path, sizeof(log_path), "%seac-exception.log", exe_path);

		FILE* file = std::fopen(log_path, "a");
		if (file != nullptr) {
			std::fprintf(file, "=== EAC emulator exception ===\n");
			std::fprintf(file, "code=0x%08X address=0x%p module=%s module_offset=0x%llX\n",
			             code, address, module_name, module_offset);
			std::fprintf(file, "exception_flags=0x%08X\n",
			             ExceptionInfo && ExceptionInfo->ExceptionRecord ? ExceptionInfo->ExceptionRecord->ExceptionFlags : 0);
			std::fprintf(file, "\n");
			std::fclose(file);
		}

		char message[512];
		std::snprintf(message, sizeof(message), "EAC emulator crashed\ncode=0x%08X at %s+0x%llX",
		              code, module_name, module_offset);
		printf("[EAC emulator] unhandled exception 0x%08X at %s+0x%llX\n", code, module_name, module_offset);
		MessageBoxA(nullptr, message, "Crashed!", MB_OK | MB_ICONERROR);
		return EXCEPTION_EXECUTE_HANDLER;
	}

   public:
	static void init() {
		SetUnhandledExceptionFilter(&TopLevelExceptionFilter);
	}
};
