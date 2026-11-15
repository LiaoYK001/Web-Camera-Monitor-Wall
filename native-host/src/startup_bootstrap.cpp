#include "startup_bootstrap.hpp"
#include "native_ui_gate.hpp"

namespace webobs::native_host {

StartupBootstrapStatus run_startup_bootstrap(const StartupBootstrapContext &context,
					   const std::function<void()> &callback) noexcept
{
	// No connected operator authorization exists for automatic bootstrap.
	// In particular, a diagnostic request must not forge operator state.
	const auto ordinary = evaluate_ui_action(UiActionKind::auto_bootstrap_on_load, UiAuthorizationState{});
	if (ordinary != UiGateStatus::refused_no_session ||
	    !context.diagnostic_requested || !context.isolated_prototype || !callback)
		return StartupBootstrapStatus::refused;
	try {
		callback();
		return StartupBootstrapStatus::diagnostic_completed;
	} catch (...) {
		return StartupBootstrapStatus::diagnostic_failed;
	}
}

} // namespace webobs::native_host
