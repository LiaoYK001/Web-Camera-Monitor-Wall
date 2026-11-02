#include "live_view_pipeline.hpp"

#include <chrono>
#include <span>
#include <utility>

namespace webobs::native_host {
namespace {

constexpr std::string_view kLiveViewPermission = "live.view";

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

LiveViewPipelineAuthorization authorize_live_view(
	SessionStore &sessions,
	std::string_view session_token,
	const std::vector<OwnershipEntry> &ledger,
	const WallSnapshotProvider &provider,
	const NativeAuthorizationBackend &backend,
	std::chrono::milliseconds total_budget,
	NativeOperationClock now) noexcept
{
	LiveViewPipelineAuthorization result;
	try {
		if (session_token.empty() || total_budget <= std::chrono::milliseconds::zero() || !provider ||
			!backend) {
			result.status = LiveViewPipelineStatus::invalid_request;
			return result;
		}
		const std::chrono::steady_clock::time_point start = now();

		// 1. Exact bound session. Missing/expired sessions and legacy unbound
		//    rows stop here with zero graph observation and zero backend calls.
		const std::optional<SessionRecord> record = sessions.validate_and_slide(session_token);
		if (!record.has_value() || !record->identity.has_value()) {
			result.status = LiveViewPipelineStatus::unauthenticated;
			return result;
		}
		const SessionIdentity identity = *record->identity;
		const std::string &principal = record->user;

		if (elapsed_or_negative(start, now()) >= total_budget) {
			result.status = LiveViewPipelineStatus::unavailable;
			return result;
		}

		// 2. Shared fail-closed ledger rules before observing the graph.
		if (!ownership_ledger_consistent(ledger)) {
			result.status = LiveViewPipelineStatus::ledger_invalid;
			return result;
		}

		// 3. Fresh observation. Provider failure or nullopt is indeterminate,
		//    decided before any backend call.
		const std::optional<WallSnapshot> snapshot = provider();
		if (!snapshot.has_value()) {
			result.status = LiveViewPipelineStatus::unavailable;
			return result;
		}

		if (elapsed_or_negative(start, now()) >= total_budget) {
			result.status = LiveViewPipelineStatus::unavailable;
			return result;
		}

		// 4. Pairing plus per-camera authorization in one fail-closed pass.
		//    decide_wall_live_view validates snapshot syntax and pairing before
		//    ever invoking the authorizer, and enforces its own post-call
		//    deadline checks; late verdicts can never authorize.
		bool binding_invalid_seen = false;
		bool budget_exhausted = false;
		bool invalid_authorizer_request = false;
		const WallLiveAuthorizer authorizer = [&](std::string_view camera_id) -> CameraPermission {
			const std::chrono::milliseconds elapsed = elapsed_or_negative(start, now());
			if (elapsed < std::chrono::milliseconds::zero() || elapsed >= total_budget) {
				budget_exhausted = true;
				return CameraPermission::unavailable;
			}
			const std::chrono::milliseconds remaining = total_budget - elapsed;
			const NativeOperationRequirement requirement{kLiveViewPermission, camera_id};
			const NativeOperationAuthorization decision =
				authorize_operation(principal, identity, std::span<const NativeOperationRequirement>{&requirement, 1},
					backend, remaining, now);
			switch (decision.status) {
			case NativeOperationStatus::allowed:
				return CameraPermission::allowed;
			case NativeOperationStatus::forbidden:
				return CameraPermission::denied;
			case NativeOperationStatus::binding_invalid:
				binding_invalid_seen = true;
				return CameraPermission::denied;
			case NativeOperationStatus::invalid_request:
				invalid_authorizer_request = true;
				return CameraPermission::unavailable;
			case NativeOperationStatus::unavailable:
				return CameraPermission::unavailable;
			}
			return CameraPermission::unavailable;
		};
		const WallLiveDecision decision = decide_wall_live_view(*snapshot, ledger, authorizer);

		switch (decision.status) {
		case WallLiveDecisionStatus::allowed:
			result.status = LiveViewPipelineStatus::allowed;
			result.camera_ids = decision.bound_camera_ids;
			result.evaluated = decision.evaluated;
			break;
		case WallLiveDecisionStatus::forbidden:
			// Identity loss mid-pipeline is an authentication failure, not a
			// permission denial; it must never look like `forbidden`.
			result.status = binding_invalid_seen ? LiveViewPipelineStatus::unauthenticated
				: LiveViewPipelineStatus::forbidden;
			break;
		case WallLiveDecisionStatus::graph_unbound:
			result.status = LiveViewPipelineStatus::graph_unbound;
			break;
		case WallLiveDecisionStatus::ledger_invalid:
			result.status = LiveViewPipelineStatus::ledger_invalid;
			break;
		case WallLiveDecisionStatus::invalid_request:
			result.status = LiveViewPipelineStatus::invalid_request;
			break;
		case WallLiveDecisionStatus::unavailable:
			result.status = budget_exhausted ? LiveViewPipelineStatus::unavailable
				: (invalid_authorizer_request ? LiveViewPipelineStatus::invalid_request
					: LiveViewPipelineStatus::unavailable);
			break;
		}
		if (binding_invalid_seen && result.status == LiveViewPipelineStatus::allowed) {
			// Defensive: an allowed result cannot coexist with observed identity
			// loss; fail closed rather than trust the composition ordering.
			result.status = LiveViewPipelineStatus::unauthenticated;
			result.camera_ids.clear();
			result.evaluated = 0;
		}
		return result;
	} catch (...) {
		result.status = LiveViewPipelineStatus::unavailable;
		result.camera_ids.clear();
		result.evaluated = 0;
		return result;
	}
}

} // namespace webobs::native_host
