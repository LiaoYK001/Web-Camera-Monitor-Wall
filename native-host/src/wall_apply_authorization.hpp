#pragma once

#include "camera_catalog_binding.hpp"
#include "source_ownership.hpp"
#include "wall_apply_plan.hpp"
#include "wall_snapshot.hpp"
#include "webobs/authentication.hpp"
#include "webobs/native_control_auth.hpp"
#include "webobs/native_operation_auth.hpp"

#include <chrono>
#include <cstddef>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs::native_host {

// Internal/unexposed composition of the existing fail-closed boundaries into
// one decision-time authorized-apply pipeline: exact bound session first
// (legacy unbound sessions yield `unauthenticated` with zero ledger checks,
// zero graph observation and zero backend calls), then whole-batch
// authorization (coarse `scene.write` on the caller-named wall resource plus
// `live.view` for every ledger camera, one authorize_operation pass with the
// remaining whole-operation budget), then a FRESH graph snapshot via the
// injected provider, and finally plan_wall_apply over that snapshot.
//
// The emitted plan is only ever produced after every gate passed; it is a
// decision-time snapshot, NOT an authorization grant, NOT an execution fence
// and NOT a reusable capability. A later executor must independently recheck
// session identity, permissions and the current graph before touching OBS:
// the snapshot-to-execution TOCTOU window stays outside this module, RBAC
// scope changes do not rotate authEpoch, and no callback can be preempted.
//
// The caller must supply the wall resource id (never a scene/source UUID as a
// cameraId), the ledger and desired entries from trusted internal adapters.
// A ledger with more than fifteen cameras cannot fit the bounded requirement
// list and fails closed as `invalid_request` with zero backend calls.

enum class WallApplyAuthorizationStatus {
	planned,
	noop,
	forbidden,
	unauthenticated,
	graph_unbound,
	ledger_invalid,
	unavailable,
	invalid_request,
};

struct WallApplyAuthorization {
	WallApplyAuthorizationStatus status = WallApplyAuthorizationStatus::invalid_request;
	// Populated only for `planned` and `noop`; every other status carries an
	// empty plan with no operations and no rollback.
	WallApplyPlan plan;
	std::size_t backend_calls = 0;
};

[[nodiscard]] WallApplyAuthorization authorize_wall_apply(
	SessionStore &sessions,
	std::string_view session_token,
	std::string_view wall_resource_id,
	const std::vector<OwnershipEntry> &ledger,
	const std::vector<WallApplyEntry> &desired,
	const std::function<std::optional<WallSnapshot>()> &provider,
	const NativeAuthorizationBackend &backend,
	std::chrono::milliseconds total_budget,
	NativeOperationClock now = [] { return std::chrono::steady_clock::now(); }) noexcept;

// Catalog-bound variant: before any session/backend work, every ledger claim
// must map to an enabled camera in the injected authoritative catalog
// observation (`invalid_catalog`/`unknown_camera`/`disabled_camera` fail closed
// with zero backend calls and zero graph observation). A `bound` catalog then
// delegates to exactly the same pipeline above; the catalog is an identity
// anchor, not a permission and not a revision binding.
[[nodiscard]] WallApplyAuthorization authorize_wall_apply_with_catalog(
	const std::vector<CameraCatalogEntry> &catalog, SessionStore &sessions, std::string_view session_token,
	std::string_view wall_resource_id, const std::vector<OwnershipEntry> &ledger,
	const std::vector<WallApplyEntry> &desired, const std::function<std::optional<WallSnapshot>()> &provider,
	const NativeAuthorizationBackend &backend, std::chrono::milliseconds total_budget,
	NativeOperationClock now = [] { return std::chrono::steady_clock::now(); }) noexcept;

} // namespace webobs::native_host
