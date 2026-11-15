#include "wall_apply_executor.hpp"

#include <string>

namespace webobs::native_host {
namespace {

constexpr std::size_t kWallSlots = 5;

bool ops_equal(const std::vector<WallApplyOperation> &a, const std::vector<WallApplyOperation> &b)
{
	if (a.size() != b.size())
		return false;
	for (std::size_t i = 0; i < a.size(); ++i) {
		if (a[i].kind != b[i].kind || a[i].camera_id != b[i].camera_id || a[i].old_uuid != b[i].old_uuid ||
		    a[i].new_uuid != b[i].new_uuid)
			return false;
	}
	return true;
}

bool undo_equal(const std::vector<WallApplyUndo> &a, const std::vector<WallApplyUndo> &b)
{
	if (a.size() != b.size())
		return false;
	for (std::size_t i = 0; i < a.size(); ++i) {
		if (a[i].kind != b[i].kind || a[i].camera_id != b[i].camera_id || a[i].uuid != b[i].uuid)
			return false;
	}
	return true;
}

// Exact inverse of one forward operation, in the order an executor replays it.
void append_undo(const WallApplyOperation &op, std::vector<WallApplyUndo> &out)
{
	switch (op.kind) {
	case WallApplyOpKind::keep:
		break;
	case WallApplyOpKind::add:
		out.push_back({WallApplyUndoKind::drop_binding, op.camera_id, op.new_uuid});
		break;
	case WallApplyOpKind::remove:
		out.push_back({WallApplyUndoKind::restore_binding, op.camera_id, op.old_uuid});
		break;
	case WallApplyOpKind::replace:
		out.push_back({WallApplyUndoKind::drop_binding, op.camera_id, op.new_uuid});
		out.push_back({WallApplyUndoKind::restore_binding, op.camera_id, op.old_uuid});
		break;
	}
}

bool operation_shape_valid(const WallApplyOperation &op)
{
	if (!ownership_camera_id_valid(op.camera_id))
		return false;
	switch (op.kind) {
	case WallApplyOpKind::keep:
		return ownership_source_uuid_valid(op.old_uuid) && op.new_uuid.empty();
	case WallApplyOpKind::replace:
		return ownership_source_uuid_valid(op.old_uuid) && ownership_source_uuid_valid(op.new_uuid) &&
		       op.old_uuid != op.new_uuid;
	case WallApplyOpKind::remove:
		return ownership_source_uuid_valid(op.old_uuid) && op.new_uuid.empty();
	case WallApplyOpKind::add:
		return op.old_uuid.empty() && ownership_source_uuid_valid(op.new_uuid);
	}
	return false;
}

bool invoke_apply(const WallApplyTarget &target, const WallApplyOperation &op)
{
	try {
		if (!target.apply)
			return false;
		return target.apply(op.kind, op.camera_id, op.old_uuid, op.new_uuid);
	} catch (...) {
		return false;
	}
}

bool invoke_undo(const WallApplyTarget &target, const WallApplyUndo &undo)
{
	try {
		if (!target.undo)
			return false;
		return target.undo(undo.kind, undo.camera_id, undo.uuid);
	} catch (...) {
		return false;
	}
}

WallApplyExecution invalid()
{
	WallApplyExecution result;
	result.status = WallApplyExecutionStatus::invalid_plan;
	return result;
}

} // namespace

WallApplyExecution execute_wall_apply(const WallApplyPlan &plan, const WallSnapshot &fresh,
				      const std::vector<OwnershipEntry> &ledger, const WallApplyTarget &target) noexcept
{
	WallApplyExecution result;
	try {
		if (plan.status != WallApplyPlanStatus::planned && plan.status != WallApplyPlanStatus::noop)
			return invalid();

		// 1. Structural self-check: operations must be well formed and the
		// journal must be the exact inverse of those operations.
		std::vector<WallApplyEntry> desired;
		std::vector<WallApplyUndo> expected_journal;
		for (const auto &op : plan.operations) {
			if (!operation_shape_valid(op))
				return invalid();
			switch (op.kind) {
			case WallApplyOpKind::keep:
				desired.push_back({op.camera_id, op.old_uuid});
				break;
			case WallApplyOpKind::replace:
			case WallApplyOpKind::add:
				desired.push_back({op.camera_id, op.new_uuid});
				break;
			case WallApplyOpKind::remove:
				break;
			}
		}
		for (auto it = plan.operations.rbegin(); it != plan.operations.rend(); ++it)
			append_undo(*it, expected_journal);
		if (!undo_equal(expected_journal, plan.rollback) || desired.size() != kWallSlots)
			return invalid();
		if (plan.status == WallApplyPlanStatus::noop && !plan.operations.empty())
			for (const auto &op : plan.operations)
				if (op.kind != WallApplyOpKind::keep)
					return invalid();

		// 2. Re-derivation against the fresh observation: a plan that is not
		// exactly reproducible from the current state is stale.
		const WallApplyPlan rederived = plan_wall_apply(fresh, ledger, desired);
		if (rederived.status != plan.status || !ops_equal(rederived.operations, plan.operations) ||
		    !undo_equal(rederived.rollback, plan.rollback)) {
			result.status = WallApplyExecutionStatus::stale_plan;
			return result;
		}
		if (plan.status == WallApplyPlanStatus::noop) {
			result.status = WallApplyExecutionStatus::noop;
			return result;
		}
		if (!target.apply || !target.undo)
			return invalid();

		// 3. Execution with a prefix journal.
		std::vector<std::vector<WallApplyUndo>> journal;
		std::size_t applied = 0;
		for (const auto &op : plan.operations) {
			if (op.kind == WallApplyOpKind::keep)
				continue;
			if (!invoke_apply(target, op)) {
				// Roll back the applied prefix, newest first.
				std::size_t undone = 0;
				for (auto it = journal.rbegin(); it != journal.rend(); ++it) {
					bool op_clean = true;
					for (const auto &undo : *it) {
						if (!invoke_undo(target, undo)) {
							++result.failed_undo_entries;
							op_clean = false;
						}
					}
					if (op_clean)
						++undone;
				}
				result.applied_operations = applied;
				result.rolled_back_operations = undone;
				result.status = result.failed_undo_entries == 0
							? WallApplyExecutionStatus::operation_failed_rolled_back
							: WallApplyExecutionStatus::operation_failed_rollback_incomplete;
				return result;
			}
			std::vector<WallApplyUndo> entry;
			append_undo(op, entry);
			journal.push_back(std::move(entry));
			++applied;
		}
		result.status = WallApplyExecutionStatus::applied;
		result.applied_operations = applied;
		return result;
	} catch (...) {
		return invalid();
	}
}

} // namespace webobs::native_host
