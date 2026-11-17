#include "copy_id_token_response.h"

#include <common/api/json_helper.h>
#include <common/api/session_id.h>

nlohmann::json copy_id_token_response::serialize(nlohmann::json& json) {
	json = response::serialize(json);
	json["result"] = result;
	json_helper::serialize(json, "json_web_token", json_web_token);
	json["product_user_id"] = product_user_id;

	return json;
}

void copy_id_token_response::deserialize(nlohmann::json json) {
	result = json["result"];
	json_helper::deserialize(json, "json_web_token", json_web_token);
	product_user_id = json["product_user_id"].get<EOS_ProductUserId>();
}

unsigned char copy_id_token_response::get_id() {
	return COPY_ID_TOKEN_RES_ID;
}
