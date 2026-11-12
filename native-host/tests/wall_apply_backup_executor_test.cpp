// Link this test with src/wall_apply_backup_executor.cpp, src/wall_apply_backup.cpp,
// src/wall_apply_executor.cpp, src/wall_apply_plan.cpp and src/source_ownership.cpp
// ONLY. Everything is injected: no OBS, Qt, filesystem or network API is used.
#include "wall_apply_backup_executor.hpp"

#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using webobs::native_host::capture_wall_apply_backup;
using webobs::native_host::execute_wall_apply_with_backup;
using webobs::native_host::OwnershipEntry;
using webobs::native_host::plan_wall_apply;
using webobs::native_host::WallApplyBackupExecution;
using webobs::native_host::WallApplyBackupExecutionStatus;
using webobs::native_host::WallApplyBackupReader;
using webobs::native_host::WallApplyBackupWriter;
using webobs::native_host::WallApplyEntry;
using webobs::native_host::WallApplyOpKind;
using webobs::native_host::WallApplyPlan;
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
// cam-0..3 unchanged, cam-4 removed, cam-5 added: one destructive operation
// (a remove followed by an add, so a forward failure can land after it).
WallApplyPlan plan_migration()
{
	return plan_wall_apply(snapshot_of(kFive), ledger_for(kFive),
			       {{"cam-0", kFive[0]},
				{"cam-1", kFive[1]},
				{"cam-2", kFive[2]},
				{"cam-3", kFive[3]},
				{"cam-5", uuid_at('6', '6')}});
}

WallApplyPlan plan_for(const std::vector<std::string> &snapshot_uuids, const std::vector<std::string> &desired_uuids)
{
	return plan_wall_apply(snapshot_of(snapshot_uuids), ledger_for(snapshot_uuids), desired_for(desired_uuids));
}

struct FakeTarget {
	std::vector<std::string> calls;
	std::size_t forward_calls = 0;
	std::size_t undo_calls = 0;
	long fail_forward_at = -1;
	long fail_undo_at = -1;

	WallApplyTarget make()
	{
		WallApplyTarget target;
		target.apply = [this](WallApplyOpKind, std::string_view camera_id, std::string_view,
				      std::string_view) {
			const auto index = static_cast<long>(forward_calls);
			++forward_calls;
			calls.push_back("apply:" + std::string(camera_id));
			return index != fail_forward_at;
		};
		target.undo = [this](WallApplyUndoKind, std::string_view camera_id, std::string_view) {
			const auto index = static_cast<long>(undo_calls);
			++undo_calls;
			calls.push_back("undo:" + std::string(camera_id));
			return index != fail_undo_at;
		};
		return target;
	}
};

struct FakeStorage {
	std::map<std::string, std::vector<unsigned char>> material;
	std::vector<std::string> reads;
	std::vector<std::string> writes;
	long fail_restore_at = -1;
	long throw_read_at = -1;
	long throw_write_at = -1;

	WallApplyBackupReader reader()
	{
		return [this](std::string_view uuid) -> std::optional<std::vector<unsigned char>> {
			const auto index = static_cast<long>(reads.size());
			reads.emplace_back(uuid);
			if (index == throw_read_at)
				throw std::runtime_error("reader exploded");
			const auto it = material.find(std::string(uuid));
			if (it == material.end())
				return std::nullopt;
			return it->second;
		};
	}

	WallApplyBackupWriter writer()
	{
		return [this](std::string_view uuid, const std::vector<unsigned char> &bytes) {
			const auto index = static_cast<long>(writes.size());
			writes.emplace_back(uuid);
			if (index == throw_write_at)
				throw std::runtime_error("writer exploded");
			const auto it = material.find(std::string(uuid));
			if (it == material.end())
				return false;
			const bool ok = it->second == bytes && index != fail_restore_at;
			return ok;
		};
	}
};

void fill_material(FakeStorage &storage)
{
	storage.material[kFive[4]] = {'s', 'e', 't', 't', 'i', 'n', 'g', 's'};
}

void test_noop_never_reads_or_writes()
{
	FakeTarget target;
	FakeStorage storage;
	const auto plan = plan_for(kFive, kFive);
	const auto result = execute_wall_apply_with_backup(plan, snapshot_of(kFive), ledger_for(kFive), target.make(),
							   storage.reader(), storage.writer());
	expect(result.status == WallApplyBackupExecutionStatus::noop, "identical wall must be noop");
	expect(target.forward_calls == 0 && target.undo_calls == 0, "noop must not touch the target");
	expect(storage.reads.empty() && storage.writes.empty(), "noop must not capture or restore material");
	expect(result.captured_entries == 0, "noop captures nothing");
}

void test_successful_migration_restores_nothing()
{
	FakeTarget target;
	FakeStorage storage;
	fill_material(storage);
	const auto plan = plan_migration();
	const auto result = execute_wall_apply_with_backup(plan, snapshot_of(kFive), ledger_for(kFive), target.make(),
							   storage.reader(), storage.writer());
	expect(result.status == WallApplyBackupExecutionStatus::applied, "removal plus add must apply");
	expect(result.captured_entries == 1, "the removed camera's material is captured");
	expect(storage.reads.size() == 1 && storage.reads[0] == kFive[4], "reader sees only the destroyed UUID");
	expect(storage.writes.empty(), "a successful apply must not restore anything");
	expect(result.restore.restored == 0 && result.restore.failed == 0, "restore counts stay zero");
}

void test_capture_failure_stops_before_target()
{
	FakeTarget target;
	FakeStorage storage; // no material for the removed camera
	const auto plan = plan_migration();
	const auto result = execute_wall_apply_with_backup(plan, snapshot_of(kFive), ledger_for(kFive), target.make(),
							   storage.reader(), storage.writer());
	expect(result.status == WallApplyBackupExecutionStatus::backup_unavailable,
	       "missing material must refuse the whole execution");
	expect(target.forward_calls == 0 && target.undo_calls == 0, "nothing is destroyed without material");
	expect(storage.reads.size() == 1, "one read attempt was made");
}

void test_throwing_reader_is_unavailable()
{
	FakeTarget target;
	FakeStorage storage;
	fill_material(storage);
	storage.throw_read_at = 0;
	const auto plan = plan_migration();
	const auto result = execute_wall_apply_with_backup(plan, snapshot_of(kFive), ledger_for(kFive), target.make(),
							   storage.reader(), storage.writer());
	expect(result.status == WallApplyBackupExecutionStatus::backup_unavailable, "reader exception fails closed");
	expect(target.forward_calls == 0, "no forward call after a failed capture");
}

void test_rollback_restores_captured_material()
{
	FakeTarget target;
	target.fail_forward_at = 1; // remove applies, add fails
	FakeStorage storage;
	fill_material(storage);
	const auto plan = plan_migration();
	const auto result = execute_wall_apply_with_backup(plan, snapshot_of(kFive), ledger_for(kFive), target.make(),
							   storage.reader(), storage.writer());
	expect(result.status == WallApplyBackupExecutionStatus::rolled_back, "full undo plus restore succeeds");
	expect(result.execution.applied_operations == 1, "one forward operation had been applied");
	expect(target.undo_calls == 1, "the remove is undone");
	expect(result.restore.restored == 1 && result.restore.complete, "the captured material is written back");
	expect(storage.writes.size() == 1 && storage.writes[0] == kFive[4], "restore targets the old UUID");
}

void test_failed_undo_skips_restore()
{
	FakeTarget target;
	target.fail_forward_at = 1;
	target.fail_undo_at = 0;
	FakeStorage storage;
	fill_material(storage);
	const auto plan = plan_migration();
	const auto result = execute_wall_apply_with_backup(plan, snapshot_of(kFive), ledger_for(kFive), target.make(),
							   storage.reader(), storage.writer());
	expect(result.status == WallApplyBackupExecutionStatus::rollback_incomplete, "failed undo is reported");
	expect(storage.writes.empty(), "unknown target state must not receive settings");
}

void test_failed_restore_is_reported()
{
	FakeTarget target;
	target.fail_forward_at = 1;
	FakeStorage storage;
	fill_material(storage);
	storage.fail_restore_at = 0;
	const auto plan = plan_migration();
	const auto result = execute_wall_apply_with_backup(plan, snapshot_of(kFive), ledger_for(kFive), target.make(),
							   storage.reader(), storage.writer());
	expect(result.status == WallApplyBackupExecutionStatus::rollback_settings_incomplete,
	       "a failed settings restore is not a full rollback");
	expect(result.restore.restored == 0 && result.restore.failed == 1, "counts report the failure");
}

void test_invalid_and_stale_plans_touch_nothing()
{
	FakeTarget target;
	FakeStorage storage;
	fill_material(storage);

	auto tampered = plan_migration();
	tampered.operations[0].new_uuid = uuid_at('9', '9'); // keep with a new UUID
	const auto invalid = execute_wall_apply_with_backup(tampered, snapshot_of(kFive), ledger_for(kFive),
							    target.make(), storage.reader(), storage.writer());
	expect(invalid.status == WallApplyBackupExecutionStatus::invalid_plan, "tampered keep is invalid");
	expect(target.forward_calls == 0 && storage.writes.empty(), "invalid plan never mutates or restores");

	const auto stale = execute_wall_apply_with_backup(plan_migration(),
							  snapshot_of({kFive[0], kFive[1], kFive[2], uuid_at('d', '9'), kFive[4]}),
							  ledger_for({kFive[0], kFive[1], kFive[2], uuid_at('d', '9'), kFive[4]}),
							  target.make(), storage.reader(), storage.writer());
	expect(stale.status == WallApplyBackupExecutionStatus::stale_plan, "stale plan is refused");
	expect(target.forward_calls == 0 && storage.writes.empty(), "stale plan never mutates or restores");
}

} // namespace

int main()
{
	try {
		test_noop_never_reads_or_writes();
		test_successful_migration_restores_nothing();
		test_capture_failure_stops_before_target();
		test_throwing_reader_is_unavailable();
		test_rollback_restores_captured_material();
		test_failed_undo_skips_restore();
		test_failed_restore_is_reported();
		test_invalid_and_stale_plans_touch_nothing();
	} catch (const std::exception &error) {
		std::cerr << "wall apply backup executor test failed: " << error.what() << '\n';
		return 1;
	}
	std::cout << "wall apply backup executor tests passed (" << checks << " checks)\n";
	return 0;
}
