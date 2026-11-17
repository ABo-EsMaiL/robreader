#include <cstdio>
#include <stdexcept>
#include <vector>

#include "../emulator_client.h"
#include "base64.hpp"
#include "common/eos/eos_anticheat_types.h"
#include "common/eos/eos_api.h"
#include "common/protocol/packets/begin_session_packet.h"
#include "common/protocol/packets/end_session_packet.h"
#include "common/protocol/packets/receive_message_packet.h"

static void dump_options_bytes(const void* data, size_t count) {
	if (data == nullptr) {
		PLOGI.printf("options raw bytes: <null>");
		return;
	}
	char dump[3 * 48 + 1] = {};
	size_t used = 0;
	const unsigned char* bytes = reinterpret_cast<const unsigned char*>(data);
	for (size_t i = 0; i < count; ++i) {
		used += static_cast<size_t>(sprintf_s(dump + used, sizeof(dump) - used, "%02x", bytes[i]));
	}
	PLOGI.printf("options raw bytes: %s", dump);
}

EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_AntiCheatClient_BeginSession(EOS_HAntiCheatClient handle, const EOS_AntiCheatClient_BeginSessionOptions* options) {
	auto instance = emulator_client::get_instance();
	if (options == nullptr || instance == nullptr) {
		PLOGF.printf("BeginSession: null options or client instance (options=%p client=%p)", (void*)options,
		             (void*)instance);
		return EOS_UnexpectedError;
	}

	dump_options_bytes(options, 48);
	PLOGI.printf("Beginning session with mode: %d", options->Mode);
	try {
		auto packet = std::make_shared<begin_session_packet>();
		packet->api_version = options->ApiVersion;
		packet->user_id = options->LocalUserId;
		packet->mode = options->Mode;
		instance->send_packet(packet);
	} catch (const std::exception& error) {
		PLOGF.printf("BeginSession: exception: %s", error.what());
	} catch (...) {
		PLOGF.printf("BeginSession: unknown exception");
	}

	return EOS_Success;
}

EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_AntiCheatClient_EndSession(EOS_HAntiCheatClient handle, const EOS_AntiCheatClient_EndSessionOptions* options) {
	auto instance = emulator_client::get_instance();
	if (options == nullptr || instance == nullptr) {
		PLOGF.printf("EndSession: null options or client instance (options=%p client=%p)", (void*)options,
		             (void*)instance);
		return EOS_UnexpectedError;
	}

	PLOGI.printf("Ending session");
	try {
		auto packet = std::make_shared<end_session_packet>();
		packet->options.ApiVersion = options->ApiVersion;
		instance->send_packet(packet);
	} catch (const std::exception& error) {
		PLOGF.printf("EndSession: exception: %s", error.what());
	} catch (...) {
		PLOGF.printf("EndSession: unknown exception");
	}

	return EOS_Success;
}

EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_AntiCheatClient_ReceiveMessageFromServer(EOS_HAntiCheatClient handle,
                                                  const EOS_AntiCheatClient_ReceiveMessageFromServerOptions* options) {
	auto instance = emulator_client::get_instance();
	if (options == nullptr || instance == nullptr) {
		PLOGF.printf("ReceiveMessageFromServer: null options or client instance (options=%p client=%p)",
		             (void*)options, (void*)instance);
		return EOS_UnexpectedError;
	}

	/* The Rob backend pushes EAC messages every ~3 s, so this runs a lot;
	 * a malformed message must never take the game down. */
	try {
		std::vector<char> message_bytes;
		if (options->Data != nullptr && options->DataLengthBytes > 0) {
			for (int i = 0; i < options->DataLengthBytes; i++) {
				message_bytes.push_back(static_cast<const char*>(options->Data)[i]);
			}
		}
		auto message_base64 = base64::encode_into<std::string>(message_bytes.begin(), message_bytes.end());

		auto packet = std::make_shared<receive_message_packet>();
		packet->api_version = options->ApiVersion;
		packet->base64_message = nullable_string(message_base64);
		packet->data_length_bytes = options->DataLengthBytes;
		instance->send_packet(packet);
	} catch (const std::exception& error) {
		PLOGF.printf("ReceiveMessageFromServer: exception: %s", error.what());
	} catch (...) {
		PLOGF.printf("ReceiveMessageFromServer: unknown exception");
	}

	return EOS_Success;
}
