#pragma once

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

class bootstrapper {
	static inline int tcp_port;
	static inline int http_port;

	static int __stdcall Dummy_WinMain();

	static void hook_winmain();

   public:
	// load the real EOS SDK so the emulator can talk to Epic
	static void start(int tcp_port, int http_port);

	// the emulator main loop (servers + EOS platform tick)
	static void run(int tcp_port, int http_port);

	static void main(int tcp_port, int http_port);
};
