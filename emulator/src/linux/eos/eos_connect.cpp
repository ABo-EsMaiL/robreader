#include "eos_connect.h"

#include <plog/Log.h>

#include "eos_utils.h"

void eos_connect::login(EOS_HConnect hConnect, EOS_Connect_LoginOptions const& options, void* data, const EOS_Connect_OnLoginCallback callback) {
	typedef void(EOS_CALL * EOS_Connect_Login)(EOS_HConnect, EOS_Connect_LoginOptions const*, void*, EOS_Connect_OnLoginCallback);
	static auto eos_connect_login = reinterpret_cast<EOS_Connect_Login>(
		eos_utils::get_eos_proc_addr("EOS_Connect_Login"));
	if (!eos_connect_login) {
		PLOGF.printf("Could not resolve EOS_Connect_Login");
		return;
	}

	eos_connect_login(hConnect, &options, data, callback);
}

EOS_ELoginStatus eos_connect::get_login_status(EOS_HConnect hConnect, EOS_ProductUserId local_user_id) {
	typedef EOS_ELoginStatus(EOS_CALL * EOS_Connect_GetLoginStatus)(EOS_HConnect, EOS_ProductUserId);
	static auto eos_connect_get_login_status = reinterpret_cast<EOS_Connect_GetLoginStatus>(
		eos_utils::get_eos_proc_addr("EOS_Connect_GetLoginStatus"));
	if (!eos_connect_get_login_status) {
		PLOGF.printf("Could not resolve EOS_Connect_GetLoginStatus");
		return 0;
	}

	return eos_connect_get_login_status(hConnect, local_user_id);
}

EOS_EResult eos_connect::copy_id_token(EOS_HConnect hConnect, EOS_Connect_CopyIdTokenOptions const& options, EOS_Connect_IdToken** out_token) {
	typedef EOS_EResult(EOS_CALL * EOS_Connect_CopyIdToken)(EOS_HConnect, EOS_Connect_CopyIdTokenOptions const*, EOS_Connect_IdToken**);
	static auto eos_connect_copy_id_token = reinterpret_cast<EOS_Connect_CopyIdToken>(
		eos_utils::get_eos_proc_addr("EOS_Connect_CopyIdToken"));
	if (!eos_connect_copy_id_token) {
		PLOGF.printf("Could not resolve EOS_Connect_CopyIdToken");
		return -1;
	}

	return eos_connect_copy_id_token(hConnect, &options, out_token);
}

void eos_connect::id_token_release(EOS_Connect_IdToken* token) {
	typedef void(EOS_CALL * EOS_Connect_IdToken_Release)(EOS_Connect_IdToken*);
	static auto eos_connect_id_token_release = reinterpret_cast<EOS_Connect_IdToken_Release>(
		eos_utils::get_eos_proc_addr("EOS_Connect_IdToken_Release"));
	if (!eos_connect_id_token_release || token == nullptr) {
		return;
	}

	eos_connect_id_token_release(token);
}
