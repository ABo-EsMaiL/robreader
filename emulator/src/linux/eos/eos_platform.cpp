#include "eos_platform.h"

#include <plog/Log.h>
#include "common/eos/eos_api.h"
#include "eos_utils.h"

EOS_HPlatform hPlatform = NULL;
void eos_platform::create_platform(EOS_Platform_Options const& options) {
	typedef EOS_HPlatform (EOS_CALL*EOS_Platform_Create)(EOS_Platform_Options const*);
	static auto eos_create_platform = reinterpret_cast<EOS_Platform_Create>(
		eos_utils::get_eos_proc_addr("EOS_Platform_Create"));
	if (!eos_create_platform) {
		PLOGF.printf("Could not resolve EOS_Platform_Create");
		return;
	}

	hPlatform = eos_create_platform(&options);
	if (!hPlatform) {
		PLOGE.printf("Failed to call EOS_Platform_Create!");
		return;
	}
	PLOGI.printf("Platform Created: product_id=%s, client_id=%s", options.ProductId, options.ClientCredentials.ClientId);
}

void eos_platform::tick() {
	typedef void (EOS_CALL*EOS_Platform_Tick)(EOS_HPlatform);
	static auto eos_platform_tick = reinterpret_cast<EOS_Platform_Tick>(
		eos_utils::get_eos_proc_addr("EOS_Platform_Tick"));
	if (!eos_platform_tick) {
		PLOGF.printf("Could not resolve EOS_Platform_Tick");
		return;
	}

	eos_platform_tick(hPlatform);
}

EOS_HConnect eos_platform::get_connect_interface() {
	typedef EOS_HConnect (EOS_CALL*EOS_Platform_GetConnectInterface)(EOS_HPlatform);
	static auto eos_platform_get_connect_interface = reinterpret_cast<EOS_Platform_GetConnectInterface>(
		eos_utils::get_eos_proc_addr("EOS_Platform_GetConnectInterface"));
	if (!eos_platform_get_connect_interface) {
		PLOGF.printf("Could not resolve EOS_Platform_GetConnectInterface");
		return 0;
	}

	EOS_HConnect hConnect = eos_platform_get_connect_interface(hPlatform);
	if (!hConnect) {
		PLOGE.printf("Failed to call EOS_Platform_GetConnectInterface!");
		return 0;
	}

	return hConnect;
}

EOS_HAntiCheatClient eos_platform::get_anticheat_client_interface() {
	typedef EOS_HAntiCheatClient (EOS_CALL*EOS_Platform_GetAntiCheatClientInterface)(EOS_HPlatform);
	static auto eos_platform_get_anticheat_client_interface = reinterpret_cast<EOS_Platform_GetAntiCheatClientInterface>(
		eos_utils::get_eos_proc_addr("EOS_Platform_GetAntiCheatClientInterface"));
	if (!eos_platform_get_anticheat_client_interface) {
		PLOGF.printf("Could not resolve EOS_Platform_GetAntiCheatClientInterface");
		return 0;
	}
	if (!hPlatform) {
		PLOGE.printf("get_anticheat_client_interface: platform not created yet");
		return 0;
	}

	/* Never cache the handle: a null result early (e.g. the anticheat client
	 * module was not initialised yet) must not be frozen into every later
	 * handler, and the SDK can hand out different handles per query. */
	EOS_HAntiCheatClient handle = eos_platform_get_anticheat_client_interface(hPlatform);
	PLOGI.printf("EOS_Platform_GetAntiCheatClientInterface -> 0x%llx", (unsigned long long)(uintptr_t)handle);
	return handle;
}

bool eos_platform::is_platform_created() {
	return hPlatform != NULL;
}
