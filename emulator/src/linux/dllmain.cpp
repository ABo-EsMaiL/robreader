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
 * Two ways for the server to take over the host process, selected by the
 * "mode" field of config.json:
 *
 *   "thread" (default, Rob Run) - the bare Rob Run exe survives forever
 *       after its E-0405 SteamInitializationError, so its game logic never
 *       runs and never needs to be stopped.  DllMain only spawns a worker
 *       thread; everything else (console, logger, the real SDK LoadLibrary,
 *       the servers) happens on that thread, outside the loader lock -
 *       AllocConsole and friends are not safe to call from DllMain.
 *
 *   "hook" (upstream design) - hook WinMain via MinHook so the server takes
 *       over before the game runs any of its own logic.  The hook has to be
 *       installed from DllMain itself, before WinMain is ever entered.
 */

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

struct server_context {
	int tcp_port;
	int http_port;
	bool use_logger;
	bool create_console;
};

/*
 * The thread-mode worker: everything that is not safe inside DllMain runs
 * here, outside the loader lock.
 */
static DWORD WINAPI server_worker(LPVOID param) {
	server_context* ctx = (server_context*)param;

	exception_handler::init();

	// The game logic is dead in thread mode, so repointing the process
	// working directory at the game folder is harmless and keeps the log
	// file (and any other relative path) next to the exe.
	std::string exe_dir = exe_relative_path("");
	if (exe_dir.size() > 0) {
		SetCurrentDirectoryA(exe_dir.c_str());
	}

	if (ctx->create_console) {
		utils::create_console();
		printf("Console Initialized (thread mode)\n");
	}
	utils::init_logger(false, ctx->use_logger ? plog::verbose : plog::none);

	bootstrapper::start(ctx->tcp_port, ctx->http_port);
	bootstrapper::run(ctx->tcp_port, ctx->http_port);
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

	// config.json next to the game exe (absolute path - the working
	// directory is not guaranteed).  Reading a file inside DllMain is safe;
	// loading DLLs and opening a console is not.
	std::optional<std::string> config = utils::read_file(exe_relative_path("config.json"));
	nlohmann::json json;
	if (config.has_value()) {
		json = nlohmann::json::parse(config.value());
	} else {
		// Write a default config and keep going with its values - unlike the
		// standalone server we must not pause or exit inside the game process.
		json["tcp"] = 7777;
		json["http"] = 7778;
		json["logger"] = true;
		json["mode"] = "thread";
		json["console"] = true;
		utils::write_file(exe_relative_path("config.json"), json.dump(4));
	}

	bool use_logger = json.value("logger", true);
	std::string mode = json.value("mode", "thread");

	if (mode == "hook") {
		// Upstream design: everything happens inside DllMain so the hook is
		// in place before WinMain is ever entered.
		exception_handler::init();
		utils::create_console();
		printf("Console Initialized (hook mode)\n");
		utils::init_logger(false, use_logger ? plog::verbose : plog::none);
		bootstrapper::main(json["tcp"].get<int>(), json["http"].get<int>());
	} else {
		// Thread design: DllMain only spawns the worker.
		static server_context ctx;
		ctx.tcp_port = json.value("tcp", 7777);
		ctx.http_port = json.value("http", 7778);
		ctx.use_logger = use_logger;
		ctx.create_console = json.value("console", true);
		HANDLE thread = CreateThread(nullptr, 0, server_worker, &ctx, 0, nullptr);
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
