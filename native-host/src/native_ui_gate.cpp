#include "native_ui_gate.hpp"

namespace webobs::native_host {

const UiActionDescriptor kUiActions[kUiActionCount] = {
	{UiActionKind::dock_refresh_sources, "Refresh existing Media Sources", false},
	{UiActionKind::dock_create_wall, "Create a new five-tile scene", true},
	{UiActionKind::dock_open_program_projector, "Open native Program projector", false},
	{UiActionKind::auto_bootstrap_on_load, "bootstrap_product_configuration", true},
	{UiActionKind::obs_native_source_editing, "OBS native source editing", true},
};

UiGateStatus evaluate_ui_action(UiActionKind kind, const UiAuthorizationState &state) noexcept
{
	try {
		if (kind == UiActionKind::obs_native_source_editing)
			return UiGateStatus::refused_outside_plugin;
		if (!state.operator_session_bound)
			return UiGateStatus::refused_no_session;

		switch (kind) {
		case UiActionKind::dock_refresh_sources:
		case UiActionKind::dock_open_program_projector:
			return UiGateStatus::allowed;
		case UiActionKind::dock_create_wall:
			if (!state.decision_ready || !state.plan_ready)
				return UiGateStatus::refused_no_decision;
			if (!state.backup_captured)
				return UiGateStatus::refused_no_backup;
			return UiGateStatus::allowed;
		case UiActionKind::auto_bootstrap_on_load:
			// The bootstrap decides the wall before any operator session exists.
			return UiGateStatus::refused_no_session;
		case UiActionKind::obs_native_source_editing:
			return UiGateStatus::refused_outside_plugin;
		}
		return UiGateStatus::refused_outside_plugin;
	} catch (...) {
		return UiGateStatus::refused_no_session;
	}
}

} // namespace webobs::native_host
