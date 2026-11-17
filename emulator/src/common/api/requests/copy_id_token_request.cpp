#include "copy_id_token_request.h"

#include "common/api/session_id.h"

nlohmann::json copy_id_token_request::serialize(nlohmann::json& json) {
	json = request::serialize(json);
	json["api_version"] = api_version;
	json["local_user_id"] = local_user_id;

	return json;
}

void copy_id_token_request::deserialize(nlohmann::json json) {
	api_version = json["api_version"];
	local_user_id = json["local_user_id"].get<EOS_ProductUserId>();
}

unsigned char copy_id_token_request::get_id() {
	return COPY_ID_TOKEN_REQ_ID;
}
