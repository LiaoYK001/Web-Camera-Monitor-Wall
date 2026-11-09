#pragma once

#include <cstddef>

namespace webobs::native_host {

// Inventory of the mutating/viewing entry points the native plugin exposes
// today, plus the one UI surface it CANNOT gate. The gate itself is an
// unexposed policy module: it answers "may this UI action proceed under the
// current operator state?". Dock create-wall fails closed, and the startup
// dispatcher always refuses ordinary automatic bootstrap. Explicit isolated
// prototype diagnostics are NOT an account authorization path. Wiring debt and
// the exact bypass surfaces are documented in docs/native-control-auth.md.
//
// Anything a user can do through OBS itself (Add Source, Properties, scene
// collection editing, hotkeys, scripts) bypasses the plugin entirely and is
// represented only as `obs_native_source_editing`: it is deliberately NOT
// gateable here and must be constrained by product/scene-collection policy.
enum class UiActionKind {
	dock_refresh_sources,      // dock button: enumerate existing ffmpeg sources
	dock_create_wall,          // dock button: create + select a five-tile wall from the combos
	dock_open_program_projector, // dock button: open the native Program projector
	auto_bootstrap_on_load,    // FINISHED_LOADING product.json/wall.json bootstrap
	obs_native_source_editing, // outside the plugin: OBS UI mutating sources/scenes
};

struct UiActionDescriptor {
	UiActionKind kind;
	const char *label; // exact plugin.cpp string or call site this entry covers
	bool mutates_wall;
};

// Every entry above, in plugin order. The build contract keeps this list in
// sync with the plugin's actual call sites.
constexpr std::size_t kUiActionCount = 5;
extern const UiActionDescriptor kUiActions[kUiActionCount];

// Operator state supplied by the (future) control layer. `decision_ready`
// means a fresh authorization decision and plan exist; `backup_captured`
// means the material for every destructive operation is already captured.
struct UiAuthorizationState {
	bool operator_session_bound = false;
	bool decision_ready = false;
	bool plan_ready = false;
	bool backup_captured = false;
};

enum class UiGateStatus {
	allowed,
	refused_no_session,
	refused_no_decision,
	refused_no_backup,
	refused_outside_plugin,
};

// Fail-closed matrix:
//  - `obs_native_source_editing` is always `refused_outside_plugin`;
//  - every other action requires a bound operator session;
//  - wall mutations additionally require a decision, a plan and captured
//    backup material;
//  - `auto_bootstrap_on_load` runs before any session exists and is therefore
//    refused; a separate explicitly isolated diagnostic dispatcher may exercise
//    legacy bootstrap without pretending to provide RBAC;
//  - unknown kinds are refused as `refused_outside_plugin`.
[[nodiscard]] UiGateStatus evaluate_ui_action(UiActionKind kind, const UiAuthorizationState &state) noexcept;

} // namespace webobs::native_host
