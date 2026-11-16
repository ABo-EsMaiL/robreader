#pragma once

#define GAME_HANDLE_NAME "ROB RUN.exe"

/*
 * The server runs in its own folder and loads the ORIGINAL Epic SDK from
 * there, because it needs the real EOS functions to open a real anti-cheat
 * session with Epic.  The game itself loads our replacement SDK from
 * ROB RUN_Data\Plugins\x86_64\ instead.
 */
#define EOS_SDK_PATH "EOSSDK-Win64-Shipping.dll"
