#pragma once

#include "common/api/request.h"
#include "common/api/response.h"

class copy_id_token_handler {
public:
	static std::shared_ptr<response> handle(std::shared_ptr<request> request);
};
