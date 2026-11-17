#pragma once

#include <cstdint>

#include "eos_api.h"

/* Subset of the real Epic SDK Connect structures needed to hand Rob Run a
 * valid ID token.  Layout/alignment must match the SDK because the game
 * marshals these straight from the DLL's memory. */

#define EOS_CONNECT_COPYIDTOKEN_API_LATEST 1
#define EOS_CONNECT_IDTOKEN_API_LATEST 1

#pragma pack(push, 8)

struct EOS_Connect_CopyIdTokenOptions {
	int32_t ApiVersion;
	EOS_ProductUserId LocalUserId;
};

struct EOS_Connect_IdToken {
	int32_t ApiVersion;
	EOS_ProductUserId ProductUserId;
	const char* JsonWebToken;
};

#pragma pack(pop)
