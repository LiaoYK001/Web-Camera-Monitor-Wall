#include "wall_apply_authorization.hpp"

#include <chrono>
#include <set>
#include <span>
#include <utility>

namespace webobs::native_host {
namespace {

constexpr std::string_view kSceneWritePermission = "scene.write";
constexpr std::string_view kLiveViewPermission = "live.view";
constexpr std::size_t kMaxLedgerCamerasForRequirements = 15;

std::chrono::milliseconds elapsed_or_negative(
	const std::chrono::steady_clock::time_point &start,
	const std::chrono::steady_clock::time_point &current) noexcept
{
	if (current < start) {
		return std::chrono::milliseconds(-1);
	}
	return std::chrono::duration_cast<std::chrono::milliseconds>(current - start);
}

} // namespace

WallApplyAuthorization authorize_wall_apply(
	SessionStore &sessions,
	std::string_view session_token,
	std::string_view wall_resource_id,
	const std::vector<OwnershipEntry> &ledger,
	const std::vector<WallApplyEntry> &desired,
	const std::function<std::optional<WallSnapshot>()> &provider,
	const NativeAuthorizationBackend &backend,
	std::chrono::milliseconds total_budget,
	NativeOperationClock now) noexcept
{
	WallApplyAuthorization result;
	try {
		if (session_token.empty() || total_budget <= std::chrono::milliseconds::zero() || !provider ||
			!backend) {
			result.status = WallApplyAuthorizationStatus::invalid_request;
			return result;
		}
		const std::chrono::steady_clock::time_point start = now();

		// 1. Exact bound session. Missing/expired sessions and legacy unbound
		//    rows stop here with zero ledger checks and zero backend calls.
		const std::optional<SessionRecord> record = sessions.validate_and_slide(session_token);
		if (!record.has_value() || !record->identity.has_value()) {
			result.status = WallApplyAuthorizationStatus::unauthenticated;
			return result;
		}
		const SessionIdentity identity = *record->identity;
		const std::string &principal = record->user;

		// 2. Wall resource identity and bounded requirement shape before any
		//    ledger work or backend call. Never a UUID as a resource id.
		if (!ownership_camera_id_valid(wall_resource_id) || ownership_source_uuid_valid(wall_resource_id) ||
			ledger.size() > kMaxLedgerCamerasForRequirements) {
			result.status = WallApplyAuthorizationStatus::invalid_request;
			return result;
		}

		// 2b. Desired entries must be exactly five with valid, duplicate-free
		//     camera ids and source UUIDs. Rejecting a malformed request here
		//     means no permission decision is ever spent on nonsense input;
		//     plan_wall_apply re-checks the same shape later as a defense.
		if (desired.size() != 5) {
			result.status = WallApplyAuthorizationStatus::invalid_request;
			return result;
		}
		{
			std::set<std::string_view> seen_cameras;
			std::set<std::string_view> seen_uuids;
			for (const WallApplyEntry &entry : desired) {
				if (!ownership_camera_id_valid(entry.camera_id) || !ownership_source_uuid_valid(entry.source_uuid) ||
					!seen_cameras.insert(entry.camera_id).second || !seen_uuids.insert(entry.source_uuid).second) {
					result.status = WallApplyAuthorizationStatus::invalid_request;
					return result;
				}
			}
		}

		// 3. Shared fail-closed ledger rules before observing the graph.
		if (!ownership_ledger_consistent(ledger)) {
			result.status = WallApplyAuthorizationStatus::ledger_invalid;
			return result;
		}

		if (elapsed_or_negative(start, now()) >= total_budget) {
			result.status = WallApplyAuthorizationStatus::unavailable;
			return result;
		}

		// 4. Whole-batch authorization in one authorize_operation pass: the
		//    coarse scene.write requirement first, then live.view per ledger
		//    camera. Any deny stops the prefix; identity loss mid-operation
		//    maps to unauthenticated, never forbidden.
		std::vector<NativeOperationRequirement> requirements;
		requirements.reserve(ledger.size() + 1);
		requirements.push_back(NativeOperationRequirement{kSceneWritePermission, wall_resource_id});
		for (const OwnershipEntry &entry : ledger) {
			requirements.push_back(NativeOperationRequirement{kLiveViewPermission, entry.camera_id});
		}
		const NativeOperationAuthorization decision = authorize_operation(
			principal, identity, std::span<const NativeOperationRequirement>{requirements}, backend, total_budget,
			now);
		result.backend_calls = decision.evaluated;
		switch (decision.status) {
		case NativeOperationStatus::allowed:
			break;
		case NativeOperationStatus::forbidden:
			result.status = WallApplyAuthorizationStatus::forbidden;
			return result;
		case NativeOperationStatus::binding_invalid:
			result.status = WallApplyAuthorizationStatus::unauthenticated;
			return result;
		case NativeOperationStatus::invalid_request:
		case NativeOperationStatus::unavailable:
			result.status = WallApplyAuthorizationStatus::unavailable;
			return result;
		}

		if (elapsed_or_negative(start, now()) >= total_budget) {
			result.status = WallApplyAuthorizationStatus::unavailable;
			return result;
		}

		// 5. Fresh observation. Provider failure or nullopt is indeterminate.
		const std::optional<WallSnapshot> snapshot = provider();
		if (!snapshot.has_value()) {
			result.status = WallApplyAuthorizationStatus::unavailable;
			return result;
		}

		if (elapsed_or_negative(start, now()) >= total_budget) {
			result.status = WallApplyAuthorizationStatus::unavailable;
			return result;
		}

		// 6. Planning over the fresh snapshot. plan_wall_apply re-checks the
		//    ledger and refuses any unowned graph; the plan is emitted only
		//    here, after every gate passed, and grants nothing at execution.
		const WallApplyPlan plan = plan_wall_apply(*snapshot, ledger, desired);
		switch (plan.status) {
		case WallApplyPlanStatus::planned:
			result.status = WallApplyAuthorizationStatus::planned;
			result.plan = std::move(plan);
			break;
		case WallApplyPlanStatus::noop:
			result.status = WallApplyAuthorizationStatus::noop;
			result.plan = std::move(plan);
			break;
		case WallApplyPlanStatus::request_invalid:
			result.status = WallApplyAuthorizationStatus::invalid_request;
			break;
		case WallApplyPlanStatus::ledger_invalid:
			result.status = WallApplyAuthorizationStatus::ledger_invalid;
			break;
		case WallApplyPlanStatus::graph_unbound:
			result.status = WallApplyAuthorizationStatus::graph_unbound;
			break;
		}
		return result;
	} catch (...) {
		result = WallApplyAuthorization{};
		result.status = WallApplyAuthorizationStatus::unavailable;
		return result;
	}
}

} // namespace webobs::native_host
