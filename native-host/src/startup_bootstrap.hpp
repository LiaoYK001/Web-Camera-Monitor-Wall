#pragma once

#include <functional>

namespace webobs::native_host {

// An explicit isolated prototype diagnostic, NOT an authorization grant.
// These flags are diagnostic identity checks only, never RBAC/session state.
// Ordinary startup ALWAYS refuses automatic configuration, even if a future
// UI policy could permit an operator action. OBS's own earlier scene restore
// is outside this dispatcher and may already have created media sources.
struct StartupBootstrapContext {
	bool diagnostic_requested = false;
	bool isolated_prototype = false;
};

enum class StartupBootstrapStatus { refused, diagnostic_completed, diagnostic_failed };

// The callback encloses ALL plugin startup backup/config/video/media/ledger
// effects. Rejected contexts never invoke it. Diagnostics do not validate a
// live apply, guarantee rollback, or turn their completion into authorization.
[[nodiscard]] StartupBootstrapStatus run_startup_bootstrap(
	const StartupBootstrapContext &context, const std::function<void()> &callback) noexcept;

} // namespace webobs::native_host
