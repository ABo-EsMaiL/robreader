#include <cstring>
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
 * the genuine Epic session and hand the game a properly filled token struct. */
EOS_DECLARE_FUNC(EOS_EResult)
DummyEOS_Connect_CopyIdToken(const EOS_Connect_CopyIdTokenOptions* options, EOS_Connect_IdToken** out_id_token) {
	if (out_id_token == nullptr) {
		return EOS_UnexpectedError;
	}
	*out_id_token = nullptr;
	if (options == nullptr) {
		return EOS_UnexpectedError;
	}

	auto request = std::make_shared<copy_id_token_request>();
	request->api_version = options->ApiVersion;
	request->local_user_id = options->LocalUserId;

	auto response = emulator_client::get_instance()->send_request<copy_id_token_response>(request);
	if (response == nullptr) {
		PLOGE.printf("CopyIdToken: no response from the emulator server");
		return EOS_UnexpectedError;
	}
	if (response->result != EOS_Success) {
		PLOGE.printf("CopyIdToken: server returned %d", response->result);
		return response->result;
	}
	const char* jwt = response->json_web_token.c_str();
	if (jwt == nullptr) {
		PLOGE.printf("CopyIdToken: server returned an empty JWT");
		return EOS_UnexpectedError;
	}

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
	if (id_token == nullptr) {
		return;
	}
	delete[] const_cast<char*>(id_token->JsonWebToken);
	delete id_token;
}
