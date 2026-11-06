// Test build only; no entry point is linked into ordinary prototype binaries.
#pragma once
#include <obs-frontend-api.h>
namespace webobs::native_host {
bool pixel_test_event(enum obs_frontend_event event);
}
