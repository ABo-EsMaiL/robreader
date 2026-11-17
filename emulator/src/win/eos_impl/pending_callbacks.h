#pragma once

#include <functional>

/* The real EOS SDK never invokes a completion delegate from a random worker
 * thread - it fires callbacks from EOS_Platform_Tick, i.e. on the game's main
 * thread.  Unity's EOS plugin assumes this and asserts (STATUS_BREAKPOINT)
 * when we call the delegate from a detached std::thread.  Queue the callback
 * here and drain it inside DummyEOS_Platform_Tick instead. */
void queue_eos_callback(std::function<void()> callback, int delay_ms = 0);
void drain_eos_callbacks();
