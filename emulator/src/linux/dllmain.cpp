#include <Windows.h>
#include <plog/Log.h>

#include <cstdio>
#include <string>

#include "bootstrapper.h"
#include "common/constants.h"
#include "common/exception_handler.hpp"
#include "common/utils.h"
#include "forwarding/forwarder.h"
#include "json.hpp"

/*
 * Absolute path of a file next to the host executable.  The bootstrapper is
 * expected to launch the game with its own folder as the working directory,
 * but nothing guarantees it - so config.json is resolved against the game
 * exe's folder instead of the current working directory.
 */
static std::string exe_relative_path(const char* file) {
	char path[MAX_PATH];
	GetModuleFileNameA(nullptr, path, MAX_PATH);
	std::string dir(path);
	size_t slash = dir.find_last_of('\\');
	if (slash != std::string::npos) {
		dir.resize(slash + 1);
	}
	return dir + file;
}

/*
 * Two ways for the server to take over the host process, selected by the
 * "mode" field of config.json:
 *
 *   "thread" (default, Rob Run) - the bare Rob Run exe survives forever
 *       after its E-0405 SteamInitializationError, so its game logic never
 *       runs and never needs to be stopped.  The server simply runs on a
 *       background thread created from DllMain: no hooks, no patched
 *       instructions, the smallest possible footprint for integrity scans.
 *
 *   "hook" (upstream design) - hook WinMain via MinHook so the server takes
 *       over before the game runs any of its own logic.  For games that
 *       would keep running past their startup error.
 */
static DWORD WINAPI server_thread(LPVOID param) {
	int* ports = (int*)param;
	bootstrapper::start(ports[0], ports[1]);
	bootstrapper::run(ports[0], ports[1]);
	return 0;
}

/*
 * The in-game entry point.  version.dll is side loaded next to the game exe
 * (UnityPlayer.dll imports VERSION.dll), so DllMain runs inside the protected
 * game process.
 */
BOOL WINAPI DllMain(HINSTANCE, DWORD fdwReason, LPVOID) {
	forwarder::setup();

	bool isRunningOnGameProcess = GetModuleHandleA(GAME_HANDLE_NAME) != nullptr;
	if (fdwReason != DLL_PROCESS_ATTACH || !isRunningOnGameProcess) {
		return TRUE;
	}

	std::optional<std::string> config = utils::read_file(exe_relative_path("config.json"));
	if (!config.has_value()) {
		// Write a default config.  Unlike the standalone server we must not
		// pause or exit here: that would take down the host game process.
		nlohmann::json json;
		json["tcp"] = 7777;
		json["http"] = 7778;
		json["logger"] = true;
		json["mode"] = "thread";
		utils::write_file(exe_relative_path("config.json"), json.dump(4));
		return TRUE;
	}

	nlohmann::json json = nlohmann::json::parse(config.value());
	bool use_logger = json["logger"];
	int tcp_port = json["tcp"].get<int>();
	int http_port = json["http"].get<int>();
	std::string mode = json.value("mode", "thread");

	if (mode != "hook") {
		// The game logic is dead in thread mode, so repointing the process
		// working directory at the game folder is harmless and makes the log
		// file (and any other relative path) land next to the exe.
		std::string exe_dir = exe_relative_path("");
		if (exe_dir.size() > 0) {
			SetCurrentDirectoryA(exe_dir.c_str());
		}
	}

	exception_handler::init();
	utils::create_console();
	printf("Console Initialized (mode: %s)\n", mode.c_str());
	utils::init_logger(false, use_logger ? plog::verbose : plog::none);

	if (mode == "hook") {
		bootstrapper::main(tcp_port, http_port);
	} else {
		static int ports[2] = {tcp_port, http_port};
		HANDLE thread = CreateThread(nullptr, 0, server_thread, ports, 0, nullptr);
		if (thread != nullptr) {
			CloseHandle(thread);
		}
	}

	return TRUE;
}

/*
 * The standalone server.  It runs in its own process (EACServer.exe) with
 * its own working directory, which holds:
 *
 *   config.json                       {"tcp":7777,"http":7778,"logger":true}
 *   EOSSDK-Win64-Shipping.dll         the ORIGINAL Epic SDK, untouched
 *
 * The emulator needs the real SDK to create a real anti-cheat session with
 * Epic; the game itself loads our replacement SDK from the Plugins folder.
 */
int main() {
	exception_handler::init();
	utils::create_console();
	printf("Console Initialized\n");

	std::optional<std::string> config = utils::read_file("config.json");
	if (!config.has_value()) {
		nlohmann::json json;
		json["tcp"] = 7777;
		json["http"] = 7778;
		json["logger"] = true;
		utils::write_file("config.json", json.dump(4));

		printf("\r\n\r");
		printf("+========================================================+\n\r");
		printf("|        Configuration file has been generated!          |\n\r");
		printf("| Edit the config.json file and restart the application. |\n\r");
		printf("+========================================================+\n\r");
		system("pause");
		return 1;
	}

	nlohmann::json json = nlohmann::json::parse(config.value());
	bool use_logger = json["logger"];
	utils::init_logger(false, use_logger ? plog::verbose : plog::none);

	printf("EAC emulator server starting (tcp %d, http %d)\n",
	       json["tcp"].get<int>(), json["http"].get<int>());

	bootstrapper::start(json["tcp"].get<int>(), json["http"].get<int>());
	bootstrapper::run(json["tcp"].get<int>(), json["http"].get<int>());
	return 0;
}
