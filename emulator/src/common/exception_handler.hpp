#pragma once

#include <winuser.h>
#include <windows.h>

#include <cstdarg>
#include <cstdio>
#include <cstring>

/*
 * The upstream project pulled in the "crashlog" library to print a nice
 * stack trace when the game or the emulator crashes.  That library changed
 * its API and headers, and it is not needed for the emulator to work, so
 * this is now a plain handler.  Everything is written to eac-exception.log
 * next to the game executable:
 *
 *   - the exception code and the module+offset it happened in
 *   - a raw stack walk (module+offset per frame) that can be matched against
 *     the .map file the CI build produces next to the DLLs
 *   - for MSVC C++ exceptions (0xE06D7363) the name of the thrown type, read
 *     out of the ThrowInfo RTTI - that is what tells apart "we threw" from
 *     "the game threw" (the crash next to InitializeEpicOnlineServices was
 *     exactly such an exception and the old log could not name it)
 *
 * Every dereference of a pointer coming from the exception goes through
 * safe_read(), which is guarded by __try/__except: crashing inside the
 * crash handler is worse than having no log at all.
 */

namespace crashlog {

/* Bounds-safe, truncation-safe append used by every formatter below. */
static size_t append_text(char* buffer, size_t buffer_size, size_t used, const char* format, ...) {
	if (buffer == nullptr || used >= buffer_size) {
		return used;
	}
	va_list arguments;
	va_start(arguments, format);
	int written = std::vsnprintf(buffer + used, buffer_size - used, format, arguments);
	va_end(arguments);
	if (written <= 0) {
		return used;
	}
	size_t next = used + static_cast<size_t>(written);
	return next < buffer_size ? next : buffer_size - 1;
}

/* Byte-wise read that survives bad pointers.  Used on every structure we
 * reach through exception-time addresses: reading garbage inside the crash
 * handler must not crash the handler itself. */
static bool safe_read(const void* address, void* buffer, size_t size) {
	__try {
		const volatile unsigned char* source = static_cast<const volatile unsigned char*>(address);
		unsigned char* destination = static_cast<unsigned char*>(buffer);
		for (size_t i = 0; i < size; ++i) {
			destination[i] = source[i];
		}
		return true;
	} __except (EXCEPTION_EXECUTE_HANDLER) {
		return false;
	}
}

template <typename T>
static bool safe_read_pod(const void* address, T& out) {
	return safe_read(address, &out, sizeof(T));
}

/* x64 MSVC RTTI: all cross-references are 32-bit image-relative offsets. */
struct ThrowInfo {
	unsigned int attributes;
	unsigned int unwind_fn;       /* RVA */
	unsigned int forward_compat;  /* RVA */
	unsigned int catchable_array; /* RVA of CatchableTypeArray */
};

struct CatchableTypeArray {
	int count;
	unsigned int types[1]; /* RVAs of CatchableType */
};

struct CatchableType {
	unsigned int properties;
	unsigned int type_descriptor; /* RVA */
	int mdisp;
	int pdisp;
	int vdispoff;
	unsigned int cd_offset;
};

/* For a MSVC C++ exception (0xE06D7363) the record carries the ThrowInfo
 * pointer (and a 0x19930520 magic in ExceptionInformation[0]); walk it to the
 * TypeDescriptor name like ".AVstd::runtime_error@@" for the (most derived
 * first) catchable types. */
static void describe_cxx_exception(const EXCEPTION_RECORD* record, char* out, size_t out_size) {
	if (record == nullptr || record->NumberParameters < 3) {
		std::snprintf(out, out_size, "<no ThrowInfo parameters>");
		return;
	}
	const unsigned long long magic = record->ExceptionInformation[0];
	if (magic != 0x19930520 && magic != 0x19930521 && magic != 0x19930522) {
		std::snprintf(out, out_size, "<unknown EH magic 0x%llX>", magic);
		return;
	}

	const void* throw_info_address = reinterpret_cast<const void*>(record->ExceptionInformation[1]);
	HMODULE module = nullptr;
	if (throw_info_address == nullptr ||
		!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
		                   static_cast<LPCSTR>(throw_info_address), &module) ||
		module == nullptr) {
		std::snprintf(out, out_size, "<ThrowInfo module not found>");
		return;
	}
	const unsigned char* base = reinterpret_cast<const unsigned char*>(module);

	ThrowInfo throw_info = {};
	if (!safe_read_pod(throw_info_address, throw_info) || throw_info.catchable_array == 0) {
		std::snprintf(out, out_size, "<ThrowInfo unreadable>");
		return;
	}

	int type_count = 0;
	if (!safe_read_pod(base + throw_info.catchable_array, type_count) || type_count <= 0) {
		std::snprintf(out, out_size, "<CatchableTypeArray unreadable>");
		return;
	}

	size_t used = 0;
	out[0] = '\0';
	const unsigned int limit = type_count > 4 ? 4u : static_cast<unsigned int>(type_count);
	for (unsigned int index = 0; index < limit; ++index) {
		unsigned int catchable_rva = 0;
		if (!safe_read_pod(base + throw_info.catchable_array + sizeof(int) + sizeof(unsigned int) * index,
		                   catchable_rva) ||
		    catchable_rva == 0) {
			break;
		}
		CatchableType catchable = {};
		if (!safe_read_pod(base + catchable_rva, catchable) || catchable.type_descriptor == 0) {
			break;
		}

		/* TypeDescriptor: <void* spare> then the NUL-terminated name. */
		char name[128] = {0};
		size_t name_length = 0;
		for (; name_length + 1 < sizeof(name); ++name_length) {
			char character = 0;
			if (!safe_read(base + catchable.type_descriptor + sizeof(void*) + name_length, &character, 1) ||
			    character == '\0') {
				break;
			}
			name[name_length] = character;
		}

		used = append_text(out, out_size, used, "%s%s", index > 0 ? " | " : "", name);
		if (used >= out_size - 1) {
			break;
		}
	}
	if (used == 0) {
		std::snprintf(out, out_size, "<type name unreadable>");
	}
}

static bool module_for_address(const void* address, char* out_name, size_t out_size, unsigned long long* out_base) {
	HMODULE module = nullptr;
	if (address == nullptr ||
		!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
		                   static_cast<LPCSTR>(address), &module) ||
		module == nullptr) {
		std::snprintf(out_name, out_size, "<unknown>");
		*out_base = 0;
		return false;
	}
	char path[MAX_PATH] = {0};
	if (GetModuleFileNameA(module, path, MAX_PATH) == 0) {
		std::snprintf(out_name, out_size, "<unknown>");
		*out_base = reinterpret_cast<unsigned long long>(module);
		return false;
	}
	char* separator = std::strrchr(path, '\\');
	std::snprintf(out_name, out_size, "%s", separator != nullptr ? separator + 1 : path);
	*out_base = reinterpret_cast<unsigned long long>(module);
	return true;
}

/* Manual x64 unwind from the crashed context: ntdll's RtlLookupFunctionEntry
 * + RtlVirtualUnwind do the walking, so dbghelp is never loaded inside the
 * crashing process.  Every frame is reported as module+offset, resolvable
 * against the .map file the CI build produces.  Returns the updated length. */
static size_t append_stack_trace(const CONTEXT* crashed_context, char* out, size_t out_size, size_t used) {
	HMODULE ntdll = GetModuleHandleA("ntdll.dll");
	typedef PRUNTIME_FUNCTION(WINAPI* lookup_function_t)(ULONG64, PULONG64, PUNWIND_HISTORY_TABLE);
	typedef VOID(WINAPI* virtual_unwind_t)(ULONG, ULONG64, ULONG64, PRUNTIME_FUNCTION, PCONTEXT, PVOID*, PULONG64,
	                                       PKNONVOLATILE_CONTEXT_POINTERS);
	lookup_function_t lookup = nullptr;
	virtual_unwind_t unwind = nullptr;
	if (ntdll != nullptr) {
		lookup = reinterpret_cast<lookup_function_t>(reinterpret_cast<void*>(
			GetProcAddress(ntdll, "RtlLookupFunctionEntry")));
		unwind = reinterpret_cast<virtual_unwind_t>(reinterpret_cast<void*>(GetProcAddress(ntdll, "RtlVirtualUnwind")));
	}

	CONTEXT context = *crashed_context; /* walk a copy */
	for (int frame = 0; frame < 24; ++frame) {
		char module_name[MAX_PATH];
		unsigned long long module_base = 0;
		module_for_address(reinterpret_cast<const void*>(context.Rip), module_name, sizeof(module_name), &module_base);
		used = append_text(out, out_size, used, "  #%d %s+0x%llX\n", frame, module_name, context.Rip - module_base);
		if (used >= out_size - 64) {
			break;
		}
		if (lookup == nullptr || unwind == nullptr || context.Rip == 0) {
			break;
		}

		ULONG64 image_base = 0;
		PRUNTIME_FUNCTION entry = lookup(context.Rip, &image_base, nullptr);
		if (entry == nullptr) {
			/* leaf function: the return address sits on top of the stack */
			ULONG64 return_address = 0;
			if (!safe_read_pod(reinterpret_cast<const void*>(context.Rsp), return_address)) {
				break;
			}
			context.Rip = return_address;
			context.Rsp += sizeof(ULONG64);
		} else {
			PVOID handler_data = nullptr;
			ULONG64 establisher_frame = 0;
			unwind(UNW_FLAG_NHANDLER, image_base, context.Rip, entry, &context, &handler_data, &establisher_frame,
			       nullptr);
		}
	}
	return used;
}

class exception_handler {
	static LONG WINAPI TopLevelExceptionFilter(EXCEPTION_POINTERS* info) {
		EXCEPTION_RECORD* record = info != nullptr ? info->ExceptionRecord : nullptr;
		CONTEXT* context = info != nullptr ? info->ContextRecord : nullptr;

		DWORD code = record != nullptr ? record->ExceptionCode : 0;
		const void* address = record != nullptr ? record->ExceptionAddress : nullptr;

		unsigned long long module_base = 0;
		char module_name[MAX_PATH];
		module_for_address(address, module_name, sizeof(module_name), &module_base);
		const unsigned long long module_offset =
			address != nullptr && module_base != 0
				? reinterpret_cast<unsigned long long>(address) - module_base
				: 0;

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

		char exception_type[512] = "<not a C++ exception>";
		if (code == 0xE06D7363) {
			describe_cxx_exception(record, exception_type, sizeof(exception_type));
		}

		char report[6144] = {0};
		size_t used = 0;
		SYSTEMTIME now;
		GetLocalTime(&now);
		used = append_text(report, sizeof(report), used,
		                   "=== EAC emulator exception ===\n"
		                   "time=%04u-%02u-%02u %02u:%02u:%02u thread=%lu\n"
		                   "code=0x%08X address=0x%p module=%s module_offset=0x%llX\n"
		                   "exception_flags=0x%08X parameters=%lu\n"
		                   "exception_type=%s\n",
		                   now.wYear, now.wMonth, now.wDay, now.wHour, now.wMinute, now.wSecond, GetCurrentThreadId(),
		                   code, address, module_name, module_offset,
		                   record != nullptr ? record->ExceptionFlags : 0,
		                   record != nullptr ? record->NumberParameters : 0, exception_type);
		if (context != nullptr) {
			used = append_text(report, sizeof(report), used, "stack (module+offset):\n");
			used = append_stack_trace(context, report, sizeof(report), used);
		}
		append_text(report, sizeof(report), used, "\n");

		/* kernel32 append - the CRT may hold locks we crashed inside of */
		HANDLE file = CreateFileA(log_path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS,
		                          FILE_ATTRIBUTE_NORMAL, nullptr);
		if (file != INVALID_HANDLE_VALUE) {
			DWORD written = 0;
			WriteFile(file, report, static_cast<DWORD>(std::strlen(report)), &written, nullptr);
			CloseHandle(file);
		}

		printf("%s", report);
		char message[768];
		std::snprintf(message, sizeof(message), "EAC emulator crashed\ncode=0x%08X at %s+0x%llX\ntype: %s", code,
		              module_name, module_offset, exception_type);
		MessageBoxA(nullptr, message, "Crashed!", MB_OK | MB_ICONERROR);
		return EXCEPTION_EXECUTE_HANDLER;
	}

   public:
	static void init() {
		SetUnhandledExceptionFilter(&TopLevelExceptionFilter);
	}
};

} // namespace crashlog

/* The rest of the code uses the plain class name. */
class exception_handler : public crashlog::exception_handler {};
