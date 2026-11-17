#pragma once

#include <cstdint>

#define EOS_Success 0
#define EOS_NS_Online 2

/* Real EOS_EResult values we need when the local emulator server cannot be
 * reached.  They have to match Epic's numbers, because the game reads them. */
#define EOS_UnexpectedError 0x7FFFFFFF
#define EOS_ELoginStatus_NotLoggedIn 0

#define EOS_EResult int
#define EOS_ENetworkStatus int

typedef uintptr_t EOS_HPlatform;
typedef uintptr_t EOS_HConnect;
typedef uintptr_t EOS_HAntiCheatClient;
typedef uintptr_t EOS_HAchievements;
typedef uintptr_t EOS_NotificationId;
typedef uintptr_t EOS_ProductUserId;
typedef uintptr_t EOS_ContinuanceToken;
typedef uintptr_t EOS_ELoginStatus;
typedef uintptr_t EOS_EAntiCheatClientMode;

#define EOS_EXTERN_C extern "C"
#define EOS_CALL __stdcall
#define EOS_DECLARE_FUNC(ret_type) EOS_EXTERN_C ret_type EOS_CALL
#define EOS_DECLARE_CALLBACK(CallbackName, ...) EOS_EXTERN_C typedef void(EOS_CALL * CallbackName)(__VA_ARGS__)
