#include <Windows.h>
#include <plog/Log.h>

#include <cstdio>

#include "bootstrapper.h"
#include "common/constants.h"
#include "common/exception_handler.hpp"
#include "common/utils.h"
#include "forwarding/forwarder.h"
#include "json.hpp"

BOOL WINAPI DllMain(HINSTANCE, DWORD fdwReason, LPVOID) {
	forwarder::setup();

	bool isRunningOnGameProcess = GetModuleHandleA(GAME_HANDLE_NAME) != nullptr;
	if (fdwReason != DLL_PROCESS_ATTACH || !isRunningOnGameProcess) {
		return TRUE;
	}
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
		exit(1);
	}

	nlohmann::json json = nlohmann::json::parse(config.value());
	bool use_logger = json["logger"];
	utils::init_logger(false, use_logger ? plog::verbose : plog::none);
	bootstrapper::main(json["tcp"], json["http"]);

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
