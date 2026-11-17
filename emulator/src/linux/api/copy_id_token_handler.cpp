#include "copy_id_token_handler.h"

#include <cstring>

#include <common/api/requests/copy_id_token_request.h>
#include <common/api/response/copy_id_token_response.h>
#include <plog/Log.h>

#include "../eos/eos_connect.h"
#include "../eos/eos_platform.h"

std::shared_ptr<response> copy_id_token_handler::handle(std::shared_ptr<request> request) {
	auto copy_request = std::static_pointer_cast<copy_id_token_request>(request);

	auto response = std::make_shared<copy_id_token_response>();
	response->result = -1;
	response->product_user_id = copy_request->local_user_id;

	EOS_HConnect connect = eos_platform::get_connect_interface();
	if (connect == 0) {
		PLOGE.printf("CopyIdToken: no connect interface");
		return response;
	}

	EOS_Connect_CopyIdTokenOptions options{};
	options.ApiVersion = copy_request->api_version;
	options.LocalUserId = copy_request->local_user_id;

	EOS_Connect_IdToken* token = nullptr;
	EOS_EResult result = eos_connect::copy_id_token(connect, options, &token);
	response->result = result;
	if (result == EOS_Success && token != nullptr) {
		if (token->JsonWebToken != nullptr) {
			response->json_web_token = nullable_string(token->JsonWebToken);
			PLOGI.printf("CopyIdToken: got JWT (%d chars)", (int)strlen(token->JsonWebToken));
		} else {
			PLOGE.printf("CopyIdToken: token has a null JWT");
		}
		response->product_user_id = token->ProductUserId;
		eos_connect::id_token_release(token);
	} else {
		PLOGE.printf("CopyIdToken: real SDK returned %d", result);
	}

	return response;
}
