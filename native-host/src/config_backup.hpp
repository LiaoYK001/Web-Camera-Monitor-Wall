#pragma once

namespace webobs::native_host {

// Best-effort snapshot of the private portable profile before this build writes
// to it. Runs once per application version when an existing profile is present;
// failures never block startup and never modify the profile.
void backup_config_for_upgrade_if_needed();

} // namespace webobs::native_host
