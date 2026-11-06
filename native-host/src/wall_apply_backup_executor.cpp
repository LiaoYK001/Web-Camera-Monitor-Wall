#include "wall_apply_backup_executor.hpp"

namespace webobs::native_host {
namespace {

WallApplyBackupExecution refuse(WallApplyBackupExecutionStatus status)
{
	WallApplyBackupExecution result;
	result.status = status;
	return result;
}

} // namespace

WallApplyBackupExecution execute_wall_apply_with_backup(
	const WallApplyPlan &plan, const WallSnapshot &fresh, const std::vector<OwnershipEntry> &ledger,
	const WallApplyTarget &target, const WallApplyBackupReader &reader,
	const WallApplyBackupWriter &writer) noexcept
{
	try {
		if (plan.status != WallApplyPlanStatus::planned && plan.status != WallApplyPlanStatus::noop)
			return refuse(WallApplyBackupExecutionStatus::invalid_plan);

		// Capture BEFORE touching the target: a failed capture must not destroy
		// anything that could no longer be restored.
		WallApplyBackup backup = capture_wall_apply_backup(plan, reader);
		if (backup.status == WallApplyBackupStatus::request_invalid)
			return refuse(WallApplyBackupExecutionStatus::invalid_plan);
		if (backup.status == WallApplyBackupStatus::unavailable)
			return refuse(WallApplyBackupExecutionStatus::backup_unavailable);

		WallApplyBackupExecution result;
		result.captured_entries = backup.entries.size();
		result.execution = execute_wall_apply(plan, fresh, ledger, target);
		switch (result.execution.status) {
		case WallApplyExecutionStatus::applied:
			result.status = WallApplyBackupExecutionStatus::applied;
			return result;
		case WallApplyExecutionStatus::noop:
			result.status = WallApplyBackupExecutionStatus::noop;
			return result;
		case WallApplyExecutionStatus::stale_plan:
			result.status = WallApplyBackupExecutionStatus::stale_plan;
			return result;
		case WallApplyExecutionStatus::invalid_plan:
			return refuse(WallApplyBackupExecutionStatus::invalid_plan);
		case WallApplyExecutionStatus::operation_failed_rollback_incomplete:
			result.status = WallApplyBackupExecutionStatus::rollback_incomplete;
			return result;
		case WallApplyExecutionStatus::operation_failed_rolled_back:
			break;
		}

		// The prefix is fully undone: every destroyed object has been recreated
		// by the target, so the captured material can now be written back.
		if (backup.entries.empty()) {
			result.status = WallApplyBackupExecutionStatus::rolled_back;
			return result;
		}
		result.restore = restore_wall_apply_backup(backup, writer);
		result.status = result.restore.complete ? WallApplyBackupExecutionStatus::rolled_back
							: WallApplyBackupExecutionStatus::rollback_settings_incomplete;
		return result;
	} catch (...) {
		return refuse(WallApplyBackupExecutionStatus::rollback_incomplete);
	}
}

} // namespace webobs::native_host
