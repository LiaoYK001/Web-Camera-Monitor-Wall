#include "wall_apply_flow.hpp"

namespace webobs::native_host {
namespace {

WallApplyFlow refuse(WallApplyFlowStatus status)
{
	WallApplyFlow result;
	result.status = status;
	return result;
}

WallApplyFlowStatus authorize_status(WallApplyAuthorizationStatus status)
{
	switch (status) {
	case WallApplyAuthorizationStatus::forbidden:
		return WallApplyFlowStatus::forbidden;
	case WallApplyAuthorizationStatus::unauthenticated:
		return WallApplyFlowStatus::unauthenticated;
	case WallApplyAuthorizationStatus::graph_unbound:
		return WallApplyFlowStatus::graph_unbound;
	case WallApplyAuthorizationStatus::ledger_invalid:
		return WallApplyFlowStatus::ledger_invalid;
	case WallApplyAuthorizationStatus::unavailable:
		return WallApplyFlowStatus::unavailable;
	case WallApplyAuthorizationStatus::invalid_request:
		return WallApplyFlowStatus::invalid_request;
	case WallApplyAuthorizationStatus::noop:
		return WallApplyFlowStatus::noop;
	case WallApplyAuthorizationStatus::planned:
		break;
	}
	return WallApplyFlowStatus::invalid_request;
}

WallApplyFlowStatus execution_status(WallApplyBackupExecutionStatus status)
{
	switch (status) {
	case WallApplyBackupExecutionStatus::applied:
		return WallApplyFlowStatus::applied;
	case WallApplyBackupExecutionStatus::noop:
		return WallApplyFlowStatus::noop;
	case WallApplyBackupExecutionStatus::rolled_back:
		return WallApplyFlowStatus::rolled_back;
	case WallApplyBackupExecutionStatus::rollback_incomplete:
		return WallApplyFlowStatus::rollback_incomplete;
	case WallApplyBackupExecutionStatus::rollback_settings_incomplete:
		return WallApplyFlowStatus::rollback_settings_incomplete;
	case WallApplyBackupExecutionStatus::stale_plan:
		return WallApplyFlowStatus::stale_plan;
	case WallApplyBackupExecutionStatus::backup_unavailable:
		return WallApplyFlowStatus::unavailable;
	case WallApplyBackupExecutionStatus::invalid_plan:
		return WallApplyFlowStatus::invalid_request;
	}
	return WallApplyFlowStatus::invalid_request;
}

} // namespace

WallApplyFlow execute_wall_apply_flow(
	const std::vector<CameraCatalogEntry> &catalog, SessionStore &sessions, std::string_view session_token,
	std::string_view wall_resource_id, const std::vector<OwnershipEntry> &ledger,
	const std::vector<WallApplyEntry> &desired, const std::function<std::optional<WallSnapshot>()> &provider,
	const NativeAuthorizationBackend &backend, const WallApplyTarget &target,
	const WallApplyBackupReader &reader, const WallApplyBackupWriter &writer, std::chrono::milliseconds total_budget,
	NativeOperationClock now) noexcept
{
	try {
		if (total_budget <= std::chrono::milliseconds(0) || !provider || !target.apply || !target.undo)
			return refuse(WallApplyFlowStatus::invalid_request);

		WallApplyFlow result;
		result.authorization = authorize_wall_apply_with_catalog(catalog, sessions, session_token, wall_resource_id,
									 ledger, desired, provider, backend, total_budget,
									 std::move(now));
		if (result.authorization.status != WallApplyAuthorizationStatus::planned) {
			result.status = authorize_status(result.authorization.status);
			return result;
		}

		// Second, independent observation for the executor's re-derivation: the
		// plan was built from an earlier snapshot and must be reproducible now.
		std::optional<WallSnapshot> fresh;
		try {
			fresh = provider();
		} catch (...) {
			fresh = std::nullopt;
		}
		if (!fresh) {
			result.status = WallApplyFlowStatus::unavailable;
			return result;
		}

		result.execution = execute_wall_apply_with_backup(result.authorization.plan, *fresh, ledger, target, reader,
								  writer);
		result.status = execution_status(result.execution.status);
		return result;
	} catch (...) {
		return refuse(WallApplyFlowStatus::unavailable);
	}
}

} // namespace webobs::native_host
