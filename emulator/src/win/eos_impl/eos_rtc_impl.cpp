#include "common/eos/eos_api.h"

#include <plog/Log.h>

/*
 * Rob Run's voice chat (Game.Global.VoiceChat.VoiceChatSettingsUpdater) walks
 * the RTC interface chain: Platform -> RTC -> Audio.  The generated stubs
 * returned 0 for every one of them, so the game's C# wrappers stayed null and
 * each frame threw E-0904 NullReferenceException inside
 * UpdateAudioInputSettings.  Hand out distinct non-null sentinel handles the
 * same way the connect/anticheat interfaces do; the audio and room calls
 * themselves stay stubs until the log shows the game needs them real.
 */

EOS_DECLARE_FUNC(EOS_HRTC)
DummyEOS_Platform_GetRTCInterface(EOS_HPlatform handle) {
	PLOG_INFO.printf("EOS_Platform_GetRTCInterface called");
	return 0x30A129C4A61;
}

EOS_DECLARE_FUNC(EOS_HRTCAdmin)
DummyEOS_Platform_GetRTCAdminInterface(EOS_HPlatform handle) {
	PLOG_INFO.printf("EOS_Platform_GetRTCAdminInterface called");
	return 0x30A129C4A62;
}

EOS_DECLARE_FUNC(EOS_HRTCAudio)
DummyEOS_RTC_GetAudioInterface(EOS_HRTC rtc) {
	PLOG_INFO.printf("EOS_RTC_GetAudioInterface called");
	return 0x30A129C4A63;
}
