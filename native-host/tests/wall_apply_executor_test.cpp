// Link this test with src/wall_apply_executor.cpp, src/wall_apply_plan.cpp and
// src/source_ownership.cpp ONLY. The executor is pure staging logic: no OBS,
// Qt, filesystem or network API. The target and the observation are injected,
// so every ordering, staleness refusal and rollback journal step is asserted
// without a real graph.
#include "wall_apply_executor.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using webobs::native_host::execute_wall_apply;
using webobs::native_host::OwnershipEntry;
using webobs::native_host::plan_wall_apply;
using webobs::native_host::WallApplyEntry;
using webobs::native_host::WallApplyExecution;
using webobs::native_host::WallApplyExecutionStatus;
using webobs::native_host::WallApplyPlan;
using webobs::native_host::WallApplyPlanStatus;
using webobs::native_host::WallApplyTarget;
using webobs::native_host::WallApplyUndoKind;
using webobs::native_host::WallSnapshot;

std::size_t checks = 0;

void expect(bool condition, const char *label)
{
	++checks;
	if (!condition)
		throw std::runtime_error(label);
}

std::string uuid_at(char marker, char tail)
{
	std::string uuid = "11111111-2222-3333-4444-555555555555";
	uuid[0] = marker;
	uuid.back() = tail;
	return uuid;
}

WallSnapshot snapshot_of(const std::vector<std::string> &uuids)
{
	WallSnapshot snapshot;
	snapshot.scene_uuid = uuid_at('1', '1');
	for (std::size_t i = 0; i < snapshot.entries.size(); ++i) {
		snapshot.entries[i].item_id = static_cast<std::int64_t>(i + 1);
		snapshot.entries[i].source_uuid = i < uuids.size() ? uuids[i] : uuid_at('f', 'f');
		snapshot.entries[i].visible = true;
	}
	return snapshot;
}

std::vector<OwnershipEntry> ledger_for(const std::vector<std::string> &uuids)
{
	std::vector<OwnershipEntry> ledger;
	for (std::size_t i = 0; i < uuids.size(); ++i)
		ledger.push_back({"cam-" + std::to_string(i), uuids[i], i + 1});
	return ledger;
}

std::vector<WallApplyEntry> desired_for(const std::vector<std::string> &uuids)
{
	std::vector<WallApplyEntry> desired;
	for (std::size_t i = 0; i < uuids.size(); ++i)
		desired.push_back({"cam-" + std::to_string(i), uuids[i]});
	return desired;
}

const std::vector<std::string> kFive = {uuid_at('a', '1'), uuid_at('b', '2'), uuid_at('c', '3'), uuid_at('d', '4'),
					uuid_at('e', '5')};

WallApplyPlan plan_for(const std::vector<std::string> &snapshot_uuids, const std::vector<std::string> &desired_uuids)
{
	return plan_wall_apply(snapshot_of(snapshot_uuids), ledger_for(snapshot_uuids), desired_for(desired_uuids));
}

struct FakeTarget {
	std::vector<std::string> calls;
	std::size_t forward_calls = 0;
	std::size_t undo_calls = 0;
	long fail_forward_at = -1; // 0-based forward call index
	long fail_undo_at = -1;    // 0-based undo call index
	bool throw_forward = false;

	WallApplyTarget make(WallApplyUndoKind = WallApplyUndoKind::restore_binding)
	{
		WallApplyTarget target;
		target.apply = [this](webobs::native_host::WallApplyOpKind kind, std::string_view camera,
				      std::string_view old_uuid, std::string_view new_uuid) {
			const std::size_t index = forward_calls++;
			calls.push_back("apply:" + std::to_string(static_cast<int>(kind)) + ":" + std::string(camera) + ":" +
					std::string(old_uuid) + ":" + std::string(new_uuid));
			if (throw_forward)
				throw std::runtime_error("target failure");
			return static_cast<long>(index) != fail_forward_at;
		};
		target.undo = [this](WallApplyUndoKind kind, std::string_view camera, std::string_view uuid) {
			const std::size_t index = undo_calls++;
			calls.push_back("undo:" + std::to_string(static_cast<int>(kind)) + ":" + std::string(camera) + ":" +
					std::string(uuid));
			return static_cast<long>(index) != fail_undo_at;
		};
		return target;
	}
};

void case_noop_makes_no_calls()
{
	const WallApplyPlan plan = plan_for(kFive, kFive);
	expect(plan.status == WallApplyPlanStatus::noop, "fixture must be a noop plan");
	FakeTarget fake;
	const WallApplyExecution result = execute_wall_apply(plan, snapshot_of(kFive), ledger_for(kFive), fake.make());
	expect(result.status == WallApplyExecutionStatus::noop, "noop plan must not execute");
	expect(result.applied_operations == 0, "noop applied count");
	expect(fake.calls.empty(), "noop must not call the target");
}

void case_replace_applies_once()
{
	std::vector<std::string> desired = kFive;
	desired[2] = uuid_at('6', '6');
	const WallApplyPlan plan = plan_for(kFive, desired);
	expect(plan.status == WallApplyPlanStatus::planned, "replace fixture must plan");
	expect(plan.operations.size() == 5, "five operations");
	FakeTarget fake;
	const WallApplyExecution result = execute_wall_apply(plan, snapshot_of(kFive), ledger_for(kFive), fake.make());
	expect(result.status == WallApplyExecutionStatus::applied, "replace must apply");
	expect(result.applied_operations == 1, "only the mutation runs");
	expect(result.failed_undo_entries == 0, "no undo entries");
	expect(fake.forward_calls == 1, "one forward call only (keeps are skipped)");
	expect(fake.undo_calls == 0, "no undo");
}

void case_stale_plan_is_refused()
{
	std::vector<std::string> desired = kFive;
	desired[2] = uuid_at('6', '6');
	const WallApplyPlan plan = plan_for(kFive, desired);
	// The graph moved: cam-2 now carries a different UUID.
	std::vector<std::string> fresh = kFive;
	fresh[2] = uuid_at('7', '7');
	FakeTarget fake;
	const WallApplyExecution result = execute_wall_apply(plan, snapshot_of(fresh), ledger_for(fresh), fake.make());
	expect(result.status == WallApplyExecutionStatus::stale_plan, "stale plan must be refused");
	expect(fake.calls.empty(), "stale plan must not touch the target");
}

void case_forward_failure_rolls_back_replace_inverse()
{
	std::vector<std::string> desired = kFive;
	desired[2] = uuid_at('6', '6');
	const WallApplyPlan plan = plan_for(kFive, desired);
	FakeTarget fake;
	fake.fail_forward_at = 0;
	const WallApplyExecution result = execute_wall_apply(plan, snapshot_of(kFive), ledger_for(kFive), fake.make());
	expect(result.status == WallApplyExecutionStatus::operation_failed_rolled_back, "failure must roll back");
	expect(result.applied_operations == 0, "nothing applied");
	expect(result.failed_undo_entries == 0, "undo clean");
	// Nothing to undo: the failing replace was never applied.
	expect(fake.undo_calls == 0, "failed first operation has no journal");
}

std::vector<WallApplyEntry> migration_desired()
{
	// cam-4 leaves the wall and cam-5 joins it, so the plan is remove + add.
	return {{"cam-0", uuid_at('a', '1')}, {"cam-1", uuid_at('b', '2')}, {"cam-2", uuid_at('c', '3')},
		{"cam-3", uuid_at('d', '4')}, {"cam-5", uuid_at('8', '8')}};
}

void case_migration_failure_rolls_back_applied_prefix()
{
	const WallApplyPlan plan =
		plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), migration_desired());
	expect(plan.status == WallApplyPlanStatus::planned, "migration fixture must plan");
	expect(plan.rollback.size() == 2, "one restore + one drop journal entry");
	FakeTarget fake;
	fake.fail_forward_at = 1;
	const WallApplyExecution result = execute_wall_apply(plan, snapshot_of(kFive), ledger_for(kFive), fake.make());
	expect(result.status == WallApplyExecutionStatus::operation_failed_rolled_back, "migration rollback");
	expect(result.applied_operations == 1, "remove applied before add failed");
	expect(result.rolled_back_operations == 1, "remove undone");
	expect(fake.undo_calls == 1, "only the remove journal replays");
	expect(fake.calls.back() == "undo:0:cam-4:" + kFive[4], "restore binding of the removed camera");
}

void case_migration_success_reports_every_mutation()
{
	const WallApplyPlan plan =
		plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), migration_desired());
	FakeTarget fake;
	const WallApplyExecution result = execute_wall_apply(plan, snapshot_of(kFive), ledger_for(kFive), fake.make());
	expect(result.status == WallApplyExecutionStatus::applied, "migration applies");
	expect(result.applied_operations == 2, "remove + add");
	expect(fake.forward_calls == 2, "two forward calls");
	expect(fake.undo_calls == 0, "no rollback on success");
}

void case_undo_failure_is_reported()
{
	const WallApplyPlan plan =
		plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), migration_desired());
	FakeTarget fake;
	fake.fail_forward_at = 1;
	fake.fail_undo_at = 0;
	const WallApplyExecution result = execute_wall_apply(plan, snapshot_of(kFive), ledger_for(kFive), fake.make());
	expect(result.status == WallApplyExecutionStatus::operation_failed_rollback_incomplete, "undo failure status");
	expect(result.failed_undo_entries == 1, "one failed undo entry");
	expect(fake.undo_calls == 1, "the single journal entry was still attempted");
}

void case_invalid_plans_are_refused_without_calls()
{
	// Tampered keep: a keep carries a new UUID.
	WallApplyPlan keep = plan_for(kFive, kFive);
	keep.status = WallApplyPlanStatus::planned;
	keep.operations[0].new_uuid = uuid_at('9', '9');
	FakeTarget fake;
	expect(execute_wall_apply(keep, snapshot_of(kFive), ledger_for(kFive), fake.make()).status ==
		       WallApplyExecutionStatus::invalid_plan,
	       "tampered keep refused");

	// Forged journal: drop one rollback entry.
	std::vector<std::string> desired = kFive;
	desired[2] = uuid_at('6', '6');
	WallApplyPlan replaced = plan_for(kFive, desired);
	expect(!replaced.rollback.empty(), "replace journal exists");
	replaced.rollback.pop_back();
	expect(execute_wall_apply(replaced, snapshot_of(kFive), ledger_for(kFive), fake.make()).status ==
		       WallApplyExecutionStatus::invalid_plan,
	       "forged journal refused");

	// Missing callbacks on a real plan.
	FakeTarget none;
	WallApplyTarget empty;
	const WallApplyPlan planned = plan_for(kFive, desired);
	expect(execute_wall_apply(planned, snapshot_of(kFive), ledger_for(kFive), empty).status ==
		       WallApplyExecutionStatus::invalid_plan,
	       "missing target callbacks refused");
	expect(fake.calls.empty(), "invalid plans never call the target");
}

void case_throwing_target_is_a_failure()
{
	std::vector<std::string> desired = kFive;
	desired[2] = uuid_at('6', '6');
	const WallApplyPlan plan = plan_for(kFive, desired);
	FakeTarget fake;
	fake.throw_forward = true;
	const WallApplyExecution result = execute_wall_apply(plan, snapshot_of(kFive), ledger_for(kFive), fake.make());
	expect(result.status == WallApplyExecutionStatus::operation_failed_rolled_back, "exception becomes rollback");
	expect(result.failed_undo_entries == 0, "clean undo");
}

} // namespace

int main()
{
	try {
		case_noop_makes_no_calls();
		case_replace_applies_once();
		case_stale_plan_is_refused();
		case_forward_failure_rolls_back_replace_inverse();
		case_migration_failure_rolls_back_applied_prefix();
		case_migration_success_reports_every_mutation();
		case_undo_failure_is_reported();
		case_invalid_plans_are_refused_without_calls();
		case_throwing_target_is_a_failure();
	} catch (const std::exception &error) {
		std::cerr << "wall apply executor test failed: " << error.what() << '\n';
		return 1;
	}
	std::cout << "wall apply executor tests passed (" << checks << " checks)\n";
	return 0;
}
