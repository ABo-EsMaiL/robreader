#include <chrono>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <vector>

#include "../emulator_client.h"
#include "common/api/requests/login_request.h"
#include "common/api/requests/login_status_request.h"
#include "common/api/response/login_response.h"
#include "common/api/response/login_status_response.h"
#include "common/eos/eos_api.h"
#include "common/eos/eos_login_types.h"
#include "common/utils.h"
#include "pending_callbacks.h"

namespace {
struct pending_callback {
	std::chrono::steady_clock::time_point ready_at;
	std::function<void()> invoke;
};

std::mutex g_callback_mutex;
std::vector<pending_callback> g_callback_queue;
}

void queue_eos_callback(std::function<void()> callback, int delay_ms) {
	std::lock_guard<std::mutex> lock(g_callback_mutex);
	g_callback_queue.push_back({
		std::chrono::steady_clock::now() + std::chrono::milliseconds(delay_ms),
		std::move(callback)
	});
}

void drain_eos_callbacks() {
	std::vector<std::function<void()>> ready;
	{
		std::lock_guard<std::mutex> lock(g_callback_mutex);
		auto now = std::chrono::steady_clock::now();
		for (auto it = g_callback_queue.begin(); it != g_callback_queue.end();) {
			if (it->ready_at <= now) {
				ready.push_back(std::move(it->invoke));
				it = g_callback_queue.erase(it);
			} else {
				++it;
			}
		}
	}

	for (auto& invoke : ready) {
		/* An exception escaping a callback would otherwise call std::terminate
		 * and abort the whole game (that is the "unhandled exception" we saw). */
		try {
			invoke();
		} catch (...) {
			PLOGE.printf("EOS callback threw an exception");
		}
	}
}

void login_callback(const EOS_Connect_OnLoginCallback completion_delegate, void* client_data, std::shared_ptr<login_response> response) {
	EOS_Connect_LoginCallbackInfo info{};
	if (response == nullptr) {
		/* the local server did not answer; tell the game the login failed
		 * instead of dereferencing a null response (that used to crash it) */
		PLOGE.printf("login failed: no response from the emulator server");
		info.ResultCode = EOS_UnexpectedError;
		info.ClientData = client_data;
		info.LocalUserId = 0;
		info.ContinuanceToken = 0;
		completion_delegate(&info);
		return;
	}
	info.ResultCode = response->result_code;
	info.ClientData = client_data;
	info.LocalUserId = response->local_user_id;
	info.ContinuanceToken = response->continuance_token;
	completion_delegate(&info);
	PLOGD.printf("Logged in successfully: user_id=%llu", (unsigned long long)info.LocalUserId);
}

EOS_DECLARE_FUNC(void)
DummyEOS_Connect_Login(EOS_HConnect handle, const EOS_Connect_LoginOptions* options, void* client_data, const EOS_Connect_OnLoginCallback completion_delegate) {
	if (options == nullptr || completion_delegate == nullptr) {
		PLOGF.printf("Connect_Login: null options or completion_delegate (options=%p delegate=%p)", (void*)options,
		             (void*)completion_delegate);
		return;
	}

	auto request = std::make_shared<login_request>();
	request->api_version = options->ApiVersion;

	request->has_credentials = options->Credentials != nullptr;
	if (options->Credentials != nullptr) {
		request->credentials.ApiVersion = options->Credentials->ApiVersion;
		request->credentials.Token = nullable_string(options->Credentials->Token);
		request->credentials.Type = options->Credentials->Type;
	}

	request->has_login_info = options->UserLoginInfo != nullptr;
	if (options->UserLoginInfo != nullptr) {
		request->user_login_info.ApiVersion = options->UserLoginInfo->ApiVersion;
		request->user_login_info.DisplayName = nullable_string(options->UserLoginInfo->DisplayName);
		request->user_login_info.NsaIdToken = nullable_string(options->UserLoginInfo->NsaIdToken);
	}

	PLOGI.printf("Requesting login to proxy");
	/* A dead server or a bad packet used to throw straight through the game.
	 * A null response is handled by login_callback (reports a failed login),
	 * so any exception simply leaves it null. */
	std::shared_ptr<login_response> response;
	auto instance = emulator_client::get_instance();
	if (instance == nullptr) {
		PLOGF.printf("Connect_Login: client instance missing");
	} else {
		try {
			response = instance->send_request<login_response>(request);
		} catch (const std::exception& error) {
			PLOGF.printf("Connect_Login: request threw: %s", error.what());
		} catch (...) {
			PLOGF.printf("Connect_Login: request threw an unknown exception");
		}
	}

	/* Fire from Platform_Tick (main thread) like the real SDK, after a short
	 * grace period so the game has finished wiring up its login handlers. */
	queue_eos_callback([completion_delegate, client_data, response]() {
		login_callback(completion_delegate, client_data, response);
	}, 400);
}

EOS_DECLARE_FUNC(EOS_ELoginStatus)
DummyEOS_Connect_GetLoginStatus(EOS_HConnect Handle, EOS_ProductUserId LocalUserId) {
	auto instance = emulator_client::get_instance();
	if (instance == nullptr) {
		PLOGF.printf("GetLoginStatus: client instance missing");
		return EOS_ELoginStatus_NotLoggedIn;
	}

	auto request = std::make_shared<login_status_request>();
	request->user_id = LocalUserId;

	try {
		auto response = instance->send_request<login_status_response>(request);
		if (response == nullptr) {
			return EOS_ELoginStatus_NotLoggedIn;
		}
		return response->status;
	} catch (const std::exception& error) {
		PLOGF.printf("GetLoginStatus: request threw: %s", error.what());
	} catch (...) {
		PLOGF.printf("GetLoginStatus: request threw an unknown exception");
	}
	return EOS_ELoginStatus_NotLoggedIn;
}
