#pragma once

#if __has_include("local_defaults.h")
#include "local_defaults.h"
#else
// Public development fallback only. Create local_defaults.h from the example
// before deploying a private recovery network.
#define METECH_RECOVERY_AP_SSID "MetechCam-Setup"
#define METECH_RECOVERY_AP_PASSWORD "change-me-2026"
#endif