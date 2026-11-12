#pragma once

#include "camera_catalog_binding.hpp"
#include "source_ownership.hpp"
#include "wall_apply_authorization.hpp"
#include "wall_apply_backup_executor.hpp"
#include "wall_apply_plan.hpp"
#include "wall_snapshot.hpp"
#include "webobs/authentication.hpp"

#include <chrono>
#include <cstddef>
#include <functional>
#include <optional>
#include <string_view>
#include <vector>

namespace webobs::native_host {

// Internal/unexposed end-to-end composition of the authorized-apply chain:
// exact bound session -> whole-batch authorization (catalog-anchored) -> fresh
// graph snapshot -> plan -> captured backup -> revalidated execution -> bounded
// settings restore after a rollback. Every gate keeps its own fail-closed
// mapping; the flow only forwards statuses, so an unauthenticated, forbidden,
// catalog/ledger/graph refusal, unavailable budget/observation or stale plan
// ends with NO target callback.
//
// Two observations are made: one by the authorization step (which produces the
// plan) and one immediately before execution (which the executor re-derives
// against). This narrows, but does not close, the snapshot-to-execution
// window, and the flow remains NOT wired to OBS, NOT an authorization grant and
// NOT an execution fence. No callback can be preempted; no atomicity,
// durability or crash-recovery guarantee is made, and the target's undo is
// responsible for recreating destroyed objects before settings are restored.
enum class WallApplyFlowStatus {
	applied,                      // every planned mutation applied
	noop,                         // desired state already matched; no target calls
	rolled_back,                  // forward failure, prefix undone, material restored
	rollback_incomplete,          // forward failure, at least one undo failed
	rollback_settings_incomplete, // prefix undone but a settings restore failed
	stale_plan,                   // observation changed between decision and execution
	unauthenticated,              // missing/legacy/corrupt bound session
	forbidden,                    // catalog disabled camera or denied permission
	graph_unbound,                // ledger claim missing from catalog/graph
	ledger_invalid,               // inconsistent ownership ledger
	unavailable,                  // budget, second observation or backup material
	invalid_request,              // malformed inputs/plan
};

struct WallApplyFlow {
	WallApplyFlowStatus status = WallApplyFlowStatus::invalid_request;
	WallApplyAuthorization authorization;
	WallApplyBackupExecution execution;
};

// `provider` is called by the authorization step and again for revalidation;
// `reader`/`writer` are only touched when the plan destroys or replaces a
// source. A `noop` decision performs exactly one observation and no execution.
[[nodiscard]] WallApplyFlow execute_wall_apply_flow(
	const std::vector<CameraCatalogEntry> &catalog, SessionStore &sessions, std::string_view session_token,
	std::string_view wall_resource_id, const std::vector<OwnershipEntry> &ledger,
	const std::vector<WallApplyEntry> &desired, const std::function<std::optional<WallSnapshot>()> &provider,
	const NativeAuthorizationBackend &backend, const WallApplyTarget &target,
	const WallApplyBackupReader &reader, const WallApplyBackupWriter &writer, std::chrono::milliseconds total_budget,
	NativeOperationClock now = [] { return std::chrono::steady_clock::now(); }) noexcept;

} // namespace webobs::native_host
