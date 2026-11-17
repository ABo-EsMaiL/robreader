#pragma once

#include <common/api/request.h>
#include <common/eos/eos_api.h>

class copy_id_token_request : public request {
public:
	int32_t api_version;
	EOS_ProductUserId local_user_id;

	nlohmann::json serialize(nlohmann::json& json) override;

	void deserialize(nlohmann::json json) override;

	unsigned char get_id() override;
};
