// Link this test with src/wall_apply_plan.cpp and src/source_ownership.cpp
// ONLY. The planner is pure diff/journal logic: no OBS, Qt, filesystem or
// network API, and it never calls inspect_existing_wall. Inputs are supplied
// directly, so every fail-closed ordering and the exact inverse rollback are
// asserted without any backend or graph.
#include "wall_apply_plan.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using webobs::native_host::OwnershipEntry;
using webobs::native_host::plan_wall_apply;
using webobs::native_host::WallApplyEntry;
using webobs::native_host::WallApplyOperation;
using webobs::native_host::WallApplyOpKind;
using webobs::native_host::WallApplyPlan;
using webobs::native_host::WallApplyPlanStatus;
using webobs::native_host::WallApplyUndoKind;
using webobs::native_host::WallSnapshot;
using webobs::native_host::WallSnapshotEntry;

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

std::vector<WallApplyEntry> desired_for(const std::vector<std::pair<std::string, std::string>> &items)
{
	std::vector<WallApplyEntry> desired;
	for (const auto &[camera, uuid] : items)
		desired.push_back({camera, uuid});
	return desired;
}

// Five canonical bound UUIDs shared across cases.
const std::vector<std::string> kFive = {uuid_at('a', '1'), uuid_at('b', '2'), uuid_at('c', '3'), uuid_at('d', '4'),
					uuid_at('e', '5')};

std::vector<WallApplyEntry> same_as_ledger()
{
	std::vector<WallApplyEntry> desired;
	for (std::size_t i = 0; i < kFive.size(); ++i)
		desired.push_back({"cam-" + std::to_string(i), kFive[i]});
	return desired;
}

void test_noop_when_identical()
{
	const auto plan = plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), same_as_ledger());
	expect(plan.status == WallApplyPlanStatus::noop, "identical state must be noop");
	expect(plan.operations.size() == 5, "noop keeps every entry as a keep operation");
	for (const auto &op : plan.operations)
		expect(op.kind == WallApplyOpKind::keep, "identical state yields only keeps");
	expect(plan.rollback.empty(), "noop has an empty rollback journal");
}

void test_replace_journal_is_exact_inverse()
{
	// cam-2 swaps to a fresh UUID; others stay.
	auto desired = same_as_ledger();
	desired[2].source_uuid = uuid_at('9', '9');
	const auto plan = plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), desired);
	expect(plan.status == WallApplyPlanStatus::planned, "one swap is planned");
	expect(plan.operations.size() == 5, "keep list keeps length 5");
	std::size_t replaces = 0;
	for (const auto &op : plan.operations) {
		if (op.kind == WallApplyOpKind::replace) {
			++replaces;
			expect(op.camera_id == "cam-2", "replace targets cam-2");
			expect(op.old_uuid == kFive[2], "replace old uuid is the ledger UUID");
			expect(op.new_uuid == uuid_at('9', '9'), "replace new uuid is the desired UUID");
		}
	}
	expect(replaces == 1, "exactly one replace operation");
	// Journal replays in reverse execution order: drop new, then restore old.
	expect(plan.rollback.size() == 2, "replace produces a two-step rollback");
	expect(plan.rollback[0].kind == WallApplyUndoKind::drop_binding && plan.rollback[0].uuid == uuid_at('9', '9'),
	       "rollback drops the new binding first");
	expect(plan.rollback[1].kind == WallApplyUndoKind::restore_binding && plan.rollback[1].uuid == kFive[2],
	       "rollback restores the old binding last");
}

void test_remove_and_add_across_different_cameras()
{
	// Migration shape: cam-0 kept, cam-1..4 removed, five new cameras added.
	std::vector<WallApplyEntry> desired;
	desired.push_back({"cam-0", kFive[0]});
	for (std::size_t i = 0; i < 4; ++i)
		desired.push_back({"new-" + std::to_string(i), uuid_at('7', static_cast<char>('a' + i))});
	const auto plan = plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), desired);
	expect(plan.status == WallApplyPlanStatus::planned, "migration shape is planned");
	std::size_t keeps = 0, removes = 0, adds = 0;
	for (const auto &op : plan.operations) {
		if (op.kind == WallApplyOpKind::keep)
			++keeps;
		else if (op.kind == WallApplyOpKind::remove)
			++removes;
		else if (op.kind == WallApplyOpKind::add)
			++adds;
	}
	expect(keeps == 1 && removes == 4 && adds == 4, "keep 1, remove 4, add 4");
	// Adds are undone first (reverse order), then the binding restorations.
	expect(plan.rollback.size() == 8, "8 rollback steps for 4 adds + 4 removes");
	expect(plan.rollback[0].kind == WallApplyUndoKind::drop_binding, "adds undone before remove restorations");
	expect(plan.rollback.back().kind == WallApplyUndoKind::restore_binding && plan.rollback.back().camera_id == "cam-1",
	       "last rollback restores the earliest removed camera");
}

void test_unbound_graph_refuses_plan()
{
	auto ledger = ledger_for(kFive);
	ledger.pop_back(); // cam-4 uuid no longer claimed
	const auto plan = plan_wall_apply(snapshot_of(kFive), ledger, same_as_ledger());
	expect(plan.status == WallApplyPlanStatus::graph_unbound, "unowned snapshot entry refuses any plan");
	expect(plan.operations.empty() && plan.rollback.empty(), "refusal exposes no partial plan");
}

void test_ledger_invalid_refuses_plan()
{
	auto ledger = ledger_for(kFive);
	ledger[1].source_uuid = ledger[0].source_uuid; // duplicate UUID violates consistency
	const auto plan = plan_wall_apply(snapshot_of(kFive), ledger, same_as_ledger());
	expect(plan.status == WallApplyPlanStatus::ledger_invalid, "inconsistent ledger refuses before classification");
}

void test_desired_stealing_another_cameras_uuid_refused()
{
	// cam-4 claims cam-3's existing UUID: exact ledger equality forbids adoption.
	auto desired = same_as_ledger();
	desired[4].source_uuid = kFive[3];
	const auto plan = plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), desired);
	expect(plan.status == WallApplyPlanStatus::request_invalid, "cross-camera UUID claim is refused");
}

void test_desired_shape_and_snapshot_syntax_refused()
{
	// Too few desired entries.
	const auto short_desired = desired_for({{"cam-0", kFive[0]}});
	expect(plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), short_desired).status ==
		       WallApplyPlanStatus::request_invalid,
	       "fewer than five desired entries refused");

	// Duplicate desired camera.
	const auto dup = desired_for({{"cam-0", kFive[0]}, {"cam-0", kFive[1]}, {"cam-2", kFive[2]}, {"cam-3", kFive[3]},
				     {"cam-4", kFive[4]}});
	expect(plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), dup).status ==
		       WallApplyPlanStatus::request_invalid,
	       "duplicate desired camera refused");

	// Bad camera syntax.
	const auto bad = desired_for({{"-lead", kFive[0]}, {"cam-1", kFive[1]}, {"cam-2", kFive[2]}, {"cam-3", kFive[3]},
				      {"cam-4", kFive[4]}});
	expect(plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), bad).status ==
		       WallApplyPlanStatus::request_invalid,
	       "leading-dash camera id refused");

	// Snapshot with duplicate UUID.
	const auto dup_uuid_snapshot = snapshot_of({kFive[0], kFive[0], kFive[1], kFive[2], kFive[3]});
	expect(plan_wall_apply(dup_uuid_snapshot, ledger_for(kFive), same_as_ledger()).status ==
		       WallApplyPlanStatus::request_invalid,
	       "duplicate snapshot UUID refused");

	// Snapshot with malformed (uppercase) UUID.
	auto upper = snapshot_of(kFive);
	upper.entries[0].source_uuid = "AAAAAAAA-2222-3333-4444-555555555555";
	expect(plan_wall_apply(upper, ledger_for(kFive), same_as_ledger()).status ==
		       WallApplyPlanStatus::request_invalid,
	       "uppercase snapshot UUID refused");
}

void test_stale_ledger_uuid_is_harmless_but_conflict_refused()
{
	// A removed old UUID stays claimed (no delete API). Re-adding a different
	// camera onto that stale UUID is refused; re-recording the same camera is
	// the executor's job and not this planner's concern.
	std::vector<OwnershipEntry> ledger = ledger_for(kFive);
	ledger.push_back({"ghost", uuid_at('8', '8'), 6}); // claims a UUID not in the snapshot
	const auto ok = plan_wall_apply(snapshot_of(kFive), ledger, same_as_ledger());
	expect(ok.status == WallApplyPlanStatus::noop, "a stale claim for an absent source does not block keeps");
	auto desired = same_as_ledger();
	desired[4].source_uuid = uuid_at('8', '8'); // try to adopt ghost's UUID
	expect(plan_wall_apply(snapshot_of(kFive), ledger, desired).status == WallApplyPlanStatus::request_invalid,
	       "adopting another camera's stale claim is refused");
}

} // namespace

int main()
{
	try {
		test_noop_when_identical();
		test_replace_journal_is_exact_inverse();
		test_remove_and_add_across_different_cameras();
		test_unbound_graph_refuses_plan();
		test_ledger_invalid_refuses_plan();
		test_desired_stealing_another_cameras_uuid_refused();
		test_desired_shape_and_snapshot_syntax_refused();
		test_stale_ledger_uuid_is_harmless_but_conflict_refused();
	} catch (const std::exception &error) {
		std::cerr << "wall apply plan test failed: " << error.what() << '\n';
		return 1;
	}
	std::cout << "wall apply plan tests passed (" << checks << " checks)\n";
	return 0;
}
