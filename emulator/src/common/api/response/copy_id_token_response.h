#pragma once

#include <common/api/response.h>
#include <common/eos/eos_api.h>
#include <nullable_string.h>

class copy_id_token_response : public response {
public:
	EOS_EResult result;
	nullable_string json_web_token;
	EOS_ProductUserId product_user_id;

	nlohmann::json serialize(nlohmann::json& json) override;

	void deserialize(nlohmann::json json) override;

	unsigned char get_id() override;
};
