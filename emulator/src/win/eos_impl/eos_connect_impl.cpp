#include <cstring>
#include <stdexcept>
#include <string>

#include "../emulator_client.h"
#include "common/api/requests/copy_id_token_request.h"
#include "common/api/response/copy_id_token_response.h"
#include "common/eos/eos_api.h"
#include "common/eos/eos_connect_types.h"

/* Rob Run calls EOS_Connect_CopyIdToken right after login to get a JWT for its
 * own backend.  The old stub returned "Success" without writing OutIdToken,
 * so the game read a garbage token and reported E-0403 EosAuthorizationFailed
 * ("CopyToken result Success").  Ask the local server for the real JWT from
 * the genuine Epic session and hand the game a properly filled token struct.
 *
 * The real signature takes the connect handle FIRST:
 *   EOS_EResult EOS_Connect_CopyIdToken(EOS_HConnect Handle,
 *       const EOS_Connect_CopyIdTokenOptions* Options,
 *       EOS_Connect_IdToken** OutIdToken);
 * Missing that parameter used to make us treat the handle as the options and
 * the options pointer as the out pointer, which wrote over the game's stack
 * and then read through the fake handle constant -> 0xC0000005. */
EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_Connect_CopyIdToken(EOS_HConnect handle, const EOS_Connect_CopyIdTokenOptions* options, EOS_Connect_IdToken** out_id_token) {
	PLOGI.printf("CopyIdToken: enter (handle=0x%llX, options=%p, out=%p)",
	             (unsigned long long)handle, (void*)options, (void*)out_id_token);
	if (out_id_token == nullptr) {
		PLOGE.printf("CopyIdToken: null out_id_token");
		return EOS_UnexpectedError;
	}
	*out_id_token = nullptr;
	if (options == nullptr) {
		PLOGE.printf("CopyIdToken: null options");
		return EOS_UnexpectedError;
	}
	/* The handle is a placeholder our GetConnectInterface returns; the real
	 * SDK would use it to find the session.  The local server owns the real
	 * session, so the handle is not dereferenced here. */

	PLOGI.printf("CopyIdToken: options api=%d user=%llu", (int)options->ApiVersion,
	             (unsigned long long)options->LocalUserId);

	auto req = std::make_shared<copy_id_token_request>();
	req->api_version = options->ApiVersion;
	req->local_user_id = options->LocalUserId;

	PLOGI.printf("CopyIdToken: sending HTTP request");
	auto instance = emulator_client::get_instance();
	if (instance == nullptr) {
		PLOGE.printf("CopyIdToken: client instance missing");
		return EOS_UnexpectedError;
	}
	std::shared_ptr<copy_id_token_response> response;
	try {
		response = instance->send_request<copy_id_token_response>(req);
	} catch (const std::exception& error) {
		PLOGE.printf("CopyIdToken: request threw: %s", error.what());
	} catch (...) {
		PLOGE.printf("CopyIdToken: request threw an unknown exception");
	}
	PLOGI.printf("CopyIdToken: HTTP request returned (response=%p)", (void*)response.get());
	if (response == nullptr) {
		PLOGE.printf("CopyIdToken: no response from the emulator server");
		return EOS_UnexpectedError;
	}
	PLOGI.printf("CopyIdToken: response result=%d", (int)response->result);
	if (response->result != EOS_Success) {
		PLOGE.printf("CopyIdToken: server returned %d", response->result);
		return response->result;
	}
	const char* jwt = response->json_web_token.c_str();
	if (jwt == nullptr) {
		PLOGE.printf("CopyIdToken: server returned an empty JWT");
		return EOS_UnexpectedError;
	}
	PLOGI.printf("CopyIdToken: got JWT of %d chars", (int)std::strlen(jwt));

	/* The token must stay alive until the game calls IdToken_Release on it. */
	std::string token_text(jwt);
	char* jwt_copy = new char[token_text.size() + 1];
	std::memcpy(jwt_copy, token_text.c_str(), token_text.size() + 1);

	auto* token = new EOS_Connect_IdToken{};
	token->ApiVersion = EOS_CONNECT_IDTOKEN_API_LATEST;
	token->ProductUserId = options->LocalUserId;
	token->JsonWebToken = jwt_copy;

	*out_id_token = token;
	PLOGI.printf("CopyIdToken: handed the game a JWT (%d chars)", (int)token_text.size());
	return EOS_Success;
}

EOS_DECLARE_FUNC(void)
DummyEOS_Connect_IdToken_Release(EOS_Connect_IdToken* id_token) {
	PLOGI.printf("CopyIdToken: IdToken_Release (%p)", (void*)id_token);
	if (id_token == nullptr) {
		return;
	}
	delete[] const_cast<char*>(id_token->JsonWebToken);
	delete id_token;
}
