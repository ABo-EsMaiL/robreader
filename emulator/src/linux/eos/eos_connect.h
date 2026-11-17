#pragma once

#include "common/eos/eos_api.h"
#include "common/eos/eos_connect_types.h"
#include "common/eos/eos_login_types.h"

class eos_connect {
public:
	static void login(EOS_HConnect hConnect, EOS_Connect_LoginOptions const& options, void* data, const EOS_Connect_OnLoginCallback callback);

	static EOS_ELoginStatus get_login_status(EOS_HConnect hConnect, EOS_ProductUserId local_user_id);

	/* Copy the real ID token (JWT) out of the genuine Epic session.  Caller
	 * must release the returned token with id_token_release. */
	static EOS_EResult copy_id_token(EOS_HConnect hConnect, EOS_Connect_CopyIdTokenOptions const& options, EOS_Connect_IdToken** out_token);

	static void id_token_release(EOS_Connect_IdToken* token);
};
