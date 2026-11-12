#pragma once

namespace webobs::native_host {

// Best-effort snapshot before this plugin's explicitly isolated diagnostic
// bootstrap, once per version. Ordinary startup no longer invokes this helper.
// OBS may already have loaded/written its profile before FINISHED_LOADING.
// Failures do not block diagnostics; this is NOT an authorized-apply backup.
void backup_config_for_upgrade_if_needed();

} // namespace webobs::native_host
