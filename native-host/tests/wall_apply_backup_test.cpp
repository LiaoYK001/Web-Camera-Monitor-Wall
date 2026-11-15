// Link this test with src/wall_apply_backup.cpp, src/wall_apply_plan.cpp and
// src/source_ownership.cpp ONLY. The backup stage is pure bounded staging
// logic: no OBS, Qt, filesystem or network API. The reader/writer are
// injected, so ordering, bounds and restore accounting are asserted without a
// real graph.
#include "wall_apply_backup.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using webobs::native_host::capture_wall_apply_backup;
using webobs::native_host::OwnershipEntry;
using webobs::native_host::plan_wall_apply;
using webobs::native_host::restore_wall_apply_backup;
using webobs::native_host::WallApplyBackup;
using webobs::native_host::WallApplyBackupStatus;
using webobs::native_host::WallApplyEntry;
using webobs::native_host::WallApplyPlan;
using webobs::native_host::WallApplyPlanStatus;
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

WallApplyPlan plan_for(const std::vector<std::string> &desired_uuids)
{
	return plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), desired_for(desired_uuids));
}

std::vector<unsigned char> bytes_of(const std::string &text)
{
	return std::vector<unsigned char>(text.begin(), text.end());
}

void case_noop_never_reads()
{
	const WallApplyPlan plan = plan_for(kFive);
	expect(plan.status == WallApplyPlanStatus::noop, "fixture is a noop plan");
	std::size_t reads = 0;
	const WallApplyBackup backup = capture_wall_apply_backup(plan, [&](std::string_view) {
		++reads;
		return std::optional<std::vector<unsigned char>>{bytes_of("x")};
	});
	expect(backup.status == WallApplyBackupStatus::noop, "noop capture");
	expect(backup.entries.empty(), "noop has no material");
	expect(reads == 0, "noop must not read");
}

void case_replace_captures_old_source()
{
	std::vector<std::string> desired = kFive;
	desired[2] = uuid_at('6', '6');
	const WallApplyPlan plan = plan_for(desired);
	expect(plan.status == WallApplyPlanStatus::planned, "replace plans");
	std::vector<std::string> reads;
	const WallApplyBackup backup = capture_wall_apply_backup(plan, [&](std::string_view uuid) {
		reads.emplace_back(uuid);
		return std::optional<std::vector<unsigned char>>{bytes_of("settings-cam-2")};
	});
	expect(backup.status == WallApplyBackupStatus::captured, "replace captured");
	expect(backup.entries.size() == 1, "one destructive operation");
	expect(backup.entries[0].camera_id == "cam-2", "entry camera");
	expect(backup.entries[0].uuid == kFive[2], "entry keeps the OLD uuid");
	expect(backup.entries[0].settings == bytes_of("settings-cam-2"), "opaque settings copied");
	expect(reads.size() == 1 && reads[0] == kFive[2], "reader consulted once for the old uuid");
}

void case_remove_and_add_capture_only_the_removed_source()
{
	// cam-4 leaves and cam-5 joins: remove + add.
	const std::vector<WallApplyEntry> desired = {{"cam-0", kFive[0]}, {"cam-1", kFive[1]}, {"cam-2", kFive[2]},
						     {"cam-3", kFive[3]}, {"cam-5", uuid_at('8', '8')}};
	const WallApplyPlan plan = plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), desired);
	expect(plan.status == WallApplyPlanStatus::planned, "migration plans");
	std::size_t reads = 0;
	const WallApplyBackup backup = capture_wall_apply_backup(plan, [&](std::string_view) {
		++reads;
		return std::optional<std::vector<unsigned char>>{bytes_of("removed")};
	});
	expect(backup.status == WallApplyBackupStatus::captured, "migration captured");
	expect(backup.entries.size() == 1, "only the remove needs material");
	expect(backup.entries[0].camera_id == "cam-4", "removed camera");
	expect(reads == 1, "add is not read");
}

void case_unreadable_source_fails_closed()
{
	std::vector<std::string> desired = kFive;
	desired[2] = uuid_at('6', '6');
	const WallApplyPlan plan = plan_for(desired);

	const WallApplyBackup nullopt = capture_wall_apply_backup(plan, [](std::string_view) {
		return std::optional<std::vector<unsigned char>>{};
	});
	expect(nullopt.status == WallApplyBackupStatus::unavailable, "missing material is unavailable");
	expect(nullopt.entries.empty(), "no partial material is kept");

	const WallApplyBackup thrown = capture_wall_apply_backup(plan, [](std::string_view) -> std::optional<
											 std::vector<unsigned char>> {
		throw std::runtime_error("reader failure");
	});
	expect(thrown.status == WallApplyBackupStatus::unavailable, "reader exception is unavailable");
	expect(thrown.entries.empty(), "no partial material after exception");
}

void case_oversized_material_fails_closed()
{
	std::vector<std::string> desired = kFive;
	desired[2] = uuid_at('6', '6');
	const WallApplyPlan plan = plan_for(desired);
	const WallApplyBackup backup = capture_wall_apply_backup(
		plan, [](std::string_view) {
			return std::optional<std::vector<unsigned char>>{std::vector<unsigned char>(
				webobs::native_host::kMaxWallApplySettingsBytes + 1, 0x41)};
		});
	expect(backup.status == WallApplyBackupStatus::unavailable, "oversized material is refused");
	expect(backup.entries.empty(), "no oversized material kept");
}

void case_invalid_plans_are_refused_without_reads()
{
	std::size_t reads = 0;
	WallApplyPlan broken;
	broken.status = WallApplyPlanStatus::graph_unbound;
	const WallApplyBackup backup = capture_wall_apply_backup(broken, [&](std::string_view) {
		++reads;
		return std::optional<std::vector<unsigned char>>{bytes_of("x")};
	});
	expect(backup.status == WallApplyBackupStatus::request_invalid, "non-plannable status refused");
	expect(reads == 0, "no reads for an invalid plan");
}

void case_restore_is_newest_first_and_reports_failures()
{
	// cam-0 replaced and cam-4 removed: two destructive operations.
	const std::vector<WallApplyEntry> desired = {{"cam-0", uuid_at('6', '6')}, {"cam-1", kFive[1]},
						     {"cam-2", kFive[2]},	 {"cam-3", kFive[3]},
						     {"cam-5", uuid_at('8', '8')}};
	const WallApplyPlan plan = plan_wall_apply(snapshot_of(kFive), ledger_for(kFive), desired);
	expect(plan.status == WallApplyPlanStatus::planned, "two destructive operations plan");

	std::size_t calls = 0;
	const WallApplyBackup backup = capture_wall_apply_backup(plan, [&](std::string_view uuid) {
		++calls;
		return std::optional<std::vector<unsigned char>>{bytes_of("blob:" + std::string(uuid))};
	});
	expect(backup.status == WallApplyBackupStatus::captured, "two destructive ops captured");
	expect(backup.entries.size() == 2, "two entries");

	std::vector<std::string> writes;
	std::size_t write_calls = 0;
	const auto writer = [&](std::string_view uuid, const std::vector<unsigned char> &) {
		writes.emplace_back(uuid);
		++write_calls;
		return write_calls != 1; // first attempted restore fails
	};
	const auto restore = restore_wall_apply_backup(backup, writer);
	expect(writes.size() == 2, "every entry attempted");
	expect(writes[0] == kFive[4], "newest destructive operation restored first");
	expect(writes[1] == kFive[0], "then the replaced source");
	expect(restore.restored == 1 && restore.failed == 1, "counts reported honestly");
	expect(!restore.complete, "incomplete restore is reported");
}

} // namespace

int main()
{
	try {
		case_noop_never_reads();
		case_replace_captures_old_source();
		case_remove_and_add_capture_only_the_removed_source();
		case_unreadable_source_fails_closed();
		case_oversized_material_fails_closed();
		case_invalid_plans_are_refused_without_reads();
		case_restore_is_newest_first_and_reports_failures();
	} catch (const std::exception &error) {
		std::cerr << "wall apply backup test failed: " << error.what() << '\n';
		return 1;
	}
	std::cout << "wall apply backup tests passed (" << checks << " checks)\n";
	return 0;
}
