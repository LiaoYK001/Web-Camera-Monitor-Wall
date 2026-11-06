#include "wall_apply_backup.hpp"

#include <set>

namespace webobs::native_host {
namespace {

bool destructive_shape_valid(const WallApplyOperation &op)
{
	if (!ownership_camera_id_valid(op.camera_id) || !ownership_source_uuid_valid(op.old_uuid))
		return false;
	if (op.kind == WallApplyOpKind::replace)
		return ownership_source_uuid_valid(op.new_uuid) && op.old_uuid != op.new_uuid;
	if (op.kind == WallApplyOpKind::remove)
		return op.new_uuid.empty();
	return false;
}

} // namespace

WallApplyBackup capture_wall_apply_backup(const WallApplyPlan &plan, const WallApplyBackupReader &reader) noexcept
{
	WallApplyBackup backup;
	try {
		if (plan.status != WallApplyPlanStatus::planned && plan.status != WallApplyPlanStatus::noop)
			return backup;
		if (plan.status == WallApplyPlanStatus::noop) {
			for (const auto &op : plan.operations)
				if (op.kind != WallApplyOpKind::keep)
					return backup;
			backup.status = WallApplyBackupStatus::noop;
			return backup;
		}
		if (!reader)
			return backup;

		std::vector<const WallApplyOperation *> destructive;
		std::set<std::string> uuids;
		for (const auto &op : plan.operations) {
			if (op.kind == WallApplyOpKind::keep || op.kind == WallApplyOpKind::add)
				continue;
			if (!destructive_shape_valid(op))
				return backup;
			if (!uuids.insert(op.old_uuid).second)
				return backup;
			destructive.push_back(&op);
		}
		if (destructive.empty()) {
			// A `planned` plan always mutates; without destructive operations the
			// only legal mutation is `add`, which needs no material.
			backup.status = WallApplyBackupStatus::noop;
			return backup;
		}

		std::size_t total = 0;
		for (const WallApplyOperation *op : destructive) {
			std::optional<std::vector<unsigned char>> settings;
			try {
				settings = reader(op->old_uuid);
			} catch (...) {
				backup.entries.clear();
				backup.status = WallApplyBackupStatus::unavailable;
				return backup;
			}
			if (!settings || settings->size() > kMaxWallApplySettingsBytes) {
				backup.entries.clear();
				backup.status = WallApplyBackupStatus::unavailable;
				return backup;
			}
			total += settings->size();
			if (total > kMaxWallApplyBackupBytes) {
				backup.entries.clear();
				backup.status = WallApplyBackupStatus::unavailable;
				return backup;
			}
			backup.entries.push_back({op->camera_id, op->old_uuid, std::move(*settings)});
		}
		backup.status = WallApplyBackupStatus::captured;
		return backup;
	} catch (...) {
		WallApplyBackup failed;
		failed.entries.clear();
		return failed;
	}
}

WallApplyRestore restore_wall_apply_backup(const WallApplyBackup &backup,
					   const WallApplyBackupWriter &writer) noexcept
{
	WallApplyRestore restore;
	try {
		if (backup.status != WallApplyBackupStatus::captured || !writer)
			return restore;
		for (auto it = backup.entries.rbegin(); it != backup.entries.rend(); ++it) {
			bool ok = false;
			try {
				ok = writer(it->uuid, it->settings);
			} catch (...) {
				ok = false;
			}
			if (ok)
				++restore.restored;
			else
				++restore.failed;
		}
		restore.complete = restore.failed == 0;
		return restore;
	} catch (...) {
		WallApplyRestore failed;
		return failed;
	}
}

} // namespace webobs::native_host
