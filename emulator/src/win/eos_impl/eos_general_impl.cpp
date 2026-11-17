#include <cstring>
#include <future>
#include <stdexcept>

#include "../emulator_client.h"
#include "../emulator_initializer.h"
#include "common/api/requests/id2string_request.h"
#include "common/api/response/id2string_response.h"
#include "common/eos/eos_api.h"
#include "common/eos/eos_general_types.h"
#include "common/protocol/packets/initialize_eos_packet.h"

EOS_DECLARE_FUNC(void)
dummy_func() {
	PLOGF.printf("This should never happened");
}

/* Some newer Epic SDK functions the game may look up by name are declared to
 * return EOS_EResult.  Returning 0 (EOS_Success) instead of leaving eax
 * undefined is safer than the plain dummy above, because the caller reads the
 * result.  Used by the "Reserved"/"Get...Status" exports added to the .def. */
EOS_DECLARE_FUNC(int)
dummy_success() {
	return 0;
}

EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_Initialize(EOS_InitializeOptions* options) {
	/* REQUIRED_CLOSE used to system("pause") + exit(1) inside the game
	 * process - a missing or broken config file must never kill the game.
	 * Fail softly: report the failure to the game and let it handle it. */
	if (options == nullptr) {
		PLOGF.printf("EOS_Initialize: options is null");
		return EOS_UnexpectedError;
	}

	EmulatorStauts status = emulator_initializer::init();
	if (status != EmulatorStauts::OK) {
		PLOGF.printf("Emulator init failed (status=%d) - reporting InitializationFailed", static_cast<int>(status));
		return EOS_UnexpectedError;
	}

	auto instance = emulator_client::get_instance();
	if (instance == nullptr) {
		PLOGF.printf("Emulator client instance missing after init");
		return EOS_UnexpectedError;
	}

	try {
		auto packet = std::make_shared<initialize_eos_packet>();
		packet->api_version = options->ApiVersion;
		packet->product_name = nullable_string(options->ProductName);
		packet->product_version = nullable_string(options->ProductVersion);
		instance->send_packet(packet);
	} catch (const std::exception& error) {
		PLOGF.printf("EOS_Initialize: exception while reporting to the server: %s", error.what());
		return EOS_UnexpectedError;
	} catch (...) {
		PLOGF.printf("EOS_Initialize: unknown exception while reporting to the server");
		return EOS_UnexpectedError;
	}

	PLOGI.printf("EOS_Initialize handled");
	return EOS_Success;
}

EOS_DECLARE_FUNC(EOS_ENetworkStatus)
DummyEOS_Platform_GetNetworkStatus(EOS_HPlatform handle) {
	return EOS_NS_Online;
}

EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_Platform_SetApplicationStatus(EOS_HPlatform handle, int newStatus) {
	PLOG_INFO.printf("EOS_Platform_SetApplicationStatus called: newStatus=%d", newStatus);
	return EOS_Success;
}

EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_Platform_SetNetworkStatus(EOS_HPlatform handle, EOS_ENetworkStatus newStatus) {
	PLOG_INFO.printf("EOS_Platform_SetNetworkStatus called: newStatus=%d", newStatus);
	return EOS_Success;
}

EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_Logging_SetCallback(void* callback) {
	return EOS_Success;
}

EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_Logging_SetLogLevel(int category, int level) {
	return EOS_Success;
}

/* The game validates the id it gets from the login callback before doing
 * anything else.  Up to now this export was an unimplemented stub returning
 * 0/undefined, so Unity asserted (0x80000003) right after a successful login.
 * Our ids are opaque non-zero values; anything non-null is "valid" for us. */
EOS_DECLARE_FUNC(bool)
DummyEOS_ProductUserId_IsValid(EOS_ProductUserId account_id) {
	return account_id != 0;
}

EOS_DECLARE_FUNC(bool)
DummyEOS_EpicAccountId_IsValid(void* account_id) {
	return account_id != nullptr;
}

EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_ProductUserId_ToString(EOS_ProductUserId account_id, char* out_buffer, int32_t* in_out_buffer_length) {
	auto request = std::make_shared<id2string_request>();
	request->user_id = account_id;

	auto response = emulator_client::get_instance()->send_request<id2string_response>(request);
	if (response == nullptr) {
		return EOS_UnexpectedError;
	}

	const char* text = response->buffer.c_str();
	if (text == nullptr || in_out_buffer_length == nullptr) {
		return EOS_UnexpectedError;
	}

	int32_t text_len = response->buffer_size;   /* characters, NUL excluded */
	if (text_len < 0) {
		text_len = static_cast<int32_t>(std::strlen(text));
	}
	int32_t need = text_len + 1;                 /* + terminating NUL        */

	/* Two-call pattern: first call has out_buffer = nullptr and only asks for
	 * the required length.  Writing through that null pointer used to AV. */
	if (out_buffer == nullptr || *in_out_buffer_length < need) {
		*in_out_buffer_length = need;
		return EOS_Success;
	}

	ZeroMemory(out_buffer, need);
	memcpy(out_buffer, text, text_len);
	out_buffer[text_len] = '\0';
	*in_out_buffer_length = text_len;
	PLOGI.printf("Writing: ProductUserId=%s len=%d", text, text_len);

	return response->result;
}

EOS_DECLARE_FUNC(bool)
DummyEOS_EResult_IsOperationComplete(EOS_EResult result) {
	return true;
}
