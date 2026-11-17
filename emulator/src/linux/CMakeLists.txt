cmake_minimum_required(VERSION 3.29)
project(EACServer)

set(linux_sources
        dllmain.cpp
        bootstrapper.cpp
        bootstrapper.h
        forwarding/exports.cpp
        forwarding/forwarder.cpp
        forwarding/forwarder.h
        servers/websocket_server.cpp
        servers/websocket_server.h
        servers/http_server.cpp
        servers/http_server.h
        eos/eos_logger.h
        eos/eos_platform.h
        eos/eos_platform.cpp
        eos/eos_utils.h
        eos/eos.cpp
        eos/eos.h
        eos/eos_connect.cpp
        eos/eos_connect.h
        eos/eos_anticheat.cpp
        eos/eos_anticheat.h
        handlers/handler_registry.h
        handlers/platform/create_platform_handler.cpp
        handlers/platform/create_platform_handler.h
        handlers/common/initialize_eos_handler.cpp
        handlers/common/initialize_eos_handler.h
        handlers/common/handshake_packet_handler.cpp
        handlers/common/handshake_packet_handler.h
        handlers/anticheat/begin_session_handler.cpp
        handlers/anticheat/begin_session_handler.h
        handlers/notification/notify_message_to_server_handler.cpp
        handlers/notification/notify_message_to_server_handler.h
        handlers/anticheat/receive_message_handler.cpp
        handlers/anticheat/receive_message_handler.h
        handlers/anticheat/end_session_handler.cpp
        handlers/anticheat/end_session_handler.h
        api/api_handler_registry.h
        api/id2string_handler.cpp
        api/id2string_handler.h
        api/login_handler.cpp
        api/login_handler.h
        api/login_status_handler.cpp
        api/login_status_handler.h
        api/copy_id_token_handler.cpp
        api/copy_id_token_handler.h
)

# The standalone server process (for experiments without the game).
add_executable(EACServer
        ${includes_deps}
        ${linux_sources}
)
target_link_libraries(EACServer hv_static)

# The side-loaded server.  Sits next to the game exe under the name
# version.dll (UnityPlayer.dll imports VERSION.dll), so the loader pulls it
# into the protected game process.  exports.def re-exports the real version
# functions (forwarded to the system copy) so the import table stays valid.
add_library(version SHARED
        ${includes_deps}
        ${linux_sources}
        exports.def
)
target_link_libraries(version hv_static)

# A .map file next to the binary makes every module+offset in eac-exception.log
# resolvable to a function name offline.
if(MSVC)
	target_link_options(EACServer PRIVATE
			"/MAP:$<TARGET_FILE_DIR:EACServer>/$<TARGET_FILE_BASE_NAME:EACServer>.map"
			"/MAPINFO:EXPORTS"
	)
	target_link_options(version PRIVATE
			"/MAP:$<TARGET_FILE_DIR:version>/$<TARGET_FILE_BASE_NAME:version>.map"
			"/MAPINFO:EXPORTS"
	)
endif()
