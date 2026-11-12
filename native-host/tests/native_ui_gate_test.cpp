// Policy matrix for the native UI gate. Pure logic: no Qt, OBS, filesystem
// or network; not a dock-click or frontend execution regression.
#include "native_ui_gate.hpp"

#include <cstdio>
#include <cstdlib>
#include <set>
#include <string>

namespace {

using webobs::native_host::evaluate_ui_action;
using webobs::native_host::kUiActionCount;
using webobs::native_host::kUiActions;
using webobs::native_host::UiActionDescriptor;
using webobs::native_host::UiActionKind;
using webobs::native_host::UiAuthorizationState;
using webobs::native_host::UiGateStatus;

void require(bool condition, const char *message)
{
	if (!condition) {
		std::fprintf(stderr, "native UI gate test failed: %s\n", message);
		std::exit(1);
	}
}

UiAuthorizationState state(bool session, bool decision, bool plan, bool backup)
{
	UiAuthorizationState value;
	value.operator_session_bound = session;
	value.decision_ready = decision;
	value.plan_ready = plan;
	value.backup_captured = backup;
	return value;
}

void test_inventory_is_complete_and_unique()
{
	require(kUiActionCount == 5, "the inventory must list all five entry points");
	std::set<int> kinds;
	bool saw_refresh = false, saw_create = false, saw_projector = false, saw_bootstrap = false, saw_editing = false;
	for (std::size_t i = 0; i < kUiActionCount; ++i) {
		const UiActionDescriptor &entry = kUiActions[i];
		require(entry.label != nullptr && entry.label[0] != '\0', "every action needs a label");
		require(kinds.insert(static_cast<int>(entry.kind)).second, "action kinds must be unique");
		switch (entry.kind) {
		case UiActionKind::dock_refresh_sources:
			saw_refresh = true;
			require(!entry.mutates_wall, "refresh must stay read-only");
			break;
		case UiActionKind::dock_create_wall:
			saw_create = true;
			require(entry.mutates_wall, "create wall mutates the graph");
			break;
		case UiActionKind::dock_open_program_projector:
			saw_projector = true;
			require(!entry.mutates_wall, "opening the projector does not mutate the wall");
			break;
		case UiActionKind::auto_bootstrap_on_load:
			saw_bootstrap = true;
			require(entry.mutates_wall, "bootstrap mutates the graph");
			break;
		case UiActionKind::obs_native_source_editing:
			saw_editing = true;
			require(entry.mutates_wall, "OBS editing mutates sources");
			break;
		}
	}
	require(saw_refresh && saw_create && saw_projector && saw_bootstrap && saw_editing,
		"the inventory must cover every known entry point");
}

void test_no_session_refuses_everything_except_outside_surface()
{
	const UiAuthorizationState none = state(false, false, false, false);
	require(evaluate_ui_action(UiActionKind::dock_refresh_sources, none) == UiGateStatus::refused_no_session,
		"refresh without session must be refused");
	require(evaluate_ui_action(UiActionKind::dock_create_wall, none) == UiGateStatus::refused_no_session,
		"create wall without session must be refused");
	require(evaluate_ui_action(UiActionKind::dock_open_program_projector, none) == UiGateStatus::refused_no_session,
		"projector without session must be refused");
	require(evaluate_ui_action(UiActionKind::auto_bootstrap_on_load, none) == UiGateStatus::refused_no_session,
		"bootstrap runs before any session and must be refused");
	require(evaluate_ui_action(UiActionKind::obs_native_source_editing, none) == UiGateStatus::refused_outside_plugin,
		"OBS-native editing is never gateable");
}

void test_session_only_allows_read_only_actions()
{
	const UiAuthorizationState session_only = state(true, false, false, false);
	require(evaluate_ui_action(UiActionKind::dock_refresh_sources, session_only) == UiGateStatus::allowed,
		"read-only refresh needs only a session");
	require(evaluate_ui_action(UiActionKind::dock_open_program_projector, session_only) == UiGateStatus::allowed,
		"opening the projector needs only a session");
	require(evaluate_ui_action(UiActionKind::dock_create_wall, session_only) == UiGateStatus::refused_no_decision,
		"mutation needs a fresh decision and a plan");
	require(evaluate_ui_action(UiActionKind::auto_bootstrap_on_load, session_only) == UiGateStatus::refused_no_session,
		"bootstrap is refused even if a session exists");
}

void test_create_wall_requires_full_chain()
{
	require(evaluate_ui_action(UiActionKind::dock_create_wall, state(true, true, false, true)) ==
			UiGateStatus::refused_no_decision,
		"a decision without a plan must be refused");
	require(evaluate_ui_action(UiActionKind::dock_create_wall, state(true, false, true, true)) ==
			UiGateStatus::refused_no_decision,
		"a plan without a decision must be refused");
	require(evaluate_ui_action(UiActionKind::dock_create_wall, state(true, true, true, false)) ==
			UiGateStatus::refused_no_backup,
		"mutation without captured material must be refused");
	require(evaluate_ui_action(UiActionKind::dock_create_wall, state(true, true, true, true)) == UiGateStatus::allowed,
		"the full session/decision/plan/backup chain is allowed");
}

void test_outside_surface_always_refused()
{
	const UiAuthorizationState full = state(true, true, true, true);
	require(evaluate_ui_action(UiActionKind::obs_native_source_editing, full) == UiGateStatus::refused_outside_plugin,
		"OBS-native editing cannot be authorized by the plugin");
}

void test_unknown_kind_fails_closed()
{
	const UiAuthorizationState full = state(true, true, true, true);
	const auto unknown = static_cast<UiActionKind>(99);
	require(evaluate_ui_action(unknown, full) == UiGateStatus::refused_outside_plugin, "unknown kinds fail closed");
}

} // namespace

int main()
{
	test_inventory_is_complete_and_unique();
	test_no_session_refuses_everything_except_outside_surface();
	test_session_only_allows_read_only_actions();
	test_create_wall_requires_full_chain();
	test_outside_surface_always_refused();
	test_unknown_kind_fails_closed();
	std::fprintf(stderr, "native UI gate tests passed\n");
	return 0;
}
