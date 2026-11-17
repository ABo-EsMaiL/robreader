#include "emulator_initializer.h"

#include <cstdio>
#include <optional>
#include <stdexcept>
#include <string>

#include "common/utils.h"
#include "win/emulator_client.h"

emulator_client* client;
EmulatorStauts emulator_initializer::init() {
	std::optional<std::string> config = utils::read_file("config.json");
	if (!config.has_value()) {
		nlohmann::json json;
		nlohmann::json ports_obj;
		json["ip"] = "192.168.XXX.XXX";
		ports_obj["tcp"] = 7777;
		ports_obj["http"] = 7778;
		json["ports"] = ports_obj;
		json["logger"] = true;
		utils::write_file("config.json", json.dump(4));

		printf("\n\r\n\r");
		printf("+========================================================+\n\r");
		printf("|        Configuration file has been generated!          |\n\r");
		printf("| Edit the config.json file and restart the application. |\n\r");
		printf("+========================================================+\n\r");
		return EmulatorStauts::REQUIRED_CLOSE;
	}

	/* A malformed or incomplete config used to escape as an uncaught nlohmann
	 * exception and kill the whole game.  Parse defensively and fall back to
	 * the documented defaults instead. */
	std::string ip = "127.0.0.1";
	int tcp_port = 7777;
	int http_port = 7778;
	bool use_logger = true;
	try {
		nlohmann::json json = nlohmann::json::parse(config.value());
		ip = json.value("ip", ip);
		use_logger = json.value("logger", true);
		if (json.contains("ports") && json["ports"].is_object()) {
			tcp_port = json["ports"].value("tcp", tcp_port);
			http_port = json["ports"].value("http", http_port);
		}
	} catch (const std::exception& error) {
		printf("config.json is invalid: %s\n", error.what());
		return EmulatorStauts::REQUIRED_CLOSE;
	}

	utils::init_logger(true, use_logger ? plog::verbose : plog::none);

	client = new emulator_client(ip, http_port);
	client->connect(tcp_port);
	return EmulatorStauts::OK;
}
