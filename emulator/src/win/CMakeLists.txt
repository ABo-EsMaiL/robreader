cmake_minimum_required(VERSION 3.29)
project(EOSSDK-Win64-Shipping)

add_library(EOSSDK-Win64-Shipping SHARED
        ${includes_deps}
        dllmain.cpp
        dummy_exports.cpp
        emulator_client.cpp
        emulator_client.h
        emulator_initializer.cpp
        emulator_initializer.h
        exports.def

        eos_impl/eos_general_impl.cpp
        eos_impl/eos_connect_impl.cpp
        eos_impl/eos_notification_impl.cpp
        eos_impl/eos_platform_impl.cpp
        eos_impl/eos_session_impl.cpp
        eos_impl/eos_anticheat_impl.cpp
        eos_impl/eos_rtc_impl.cpp

        handler/handlers/client_packet_handler.cpp
        handler/handlers/client_packet_handler.h
        handler/packet_handler.h
        handler/handler_registry.cpp
        handler/handler_registry.h

        sock/packet_sender.cpp
        sock/packet_sender.h
        sock/websocket_client.cpp
        sock/websocket_client.h
)
target_link_libraries(EOSSDK-Win64-Shipping hv_static)

# A .map file next to the DLL makes every module+offset in eac-exception.log
# resolvable to a function name offline.
if(MSVC)
	target_link_options(EOSSDK-Win64-Shipping PRIVATE
			"/MAP:$<TARGET_FILE_DIR:EOSSDK-Win64-Shipping>/$<TARGET_FILE_BASE_NAME:EOSSDK-Win64-Shipping>.map"
			"/MAPINFO:EXPORTS"
	)
endif()
