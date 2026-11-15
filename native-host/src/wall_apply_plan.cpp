#include "wall_apply_plan.hpp"

#include <algorithm>
#include <map>
#include <set>

namespace webobs::native_host {
namespace {
constexpr std::size_t kWallSlots = 5;

bool desired_shape_valid(const std::vector<WallApplyEntry> &desired)
{
	if (desired.size() != kWallSlots)
		return false;
	std::set<std::string> cameras;
	std::set<std::string> uuids;
	for (const auto &entry : desired) {
		if (!ownership_camera_id_valid(entry.camera_id) || !ownership_source_uuid_valid(entry.source_uuid))
			return false;
		if (!cameras.insert(entry.camera_id).second || !uuids.insert(entry.source_uuid).second)
			return false;
	}
	return true;
}
} // namespace

WallApplyPlan plan_wall_apply(const WallSnapshot &snapshot, const std::vector<OwnershipEntry> &ledger,
			      const std::vector<WallApplyEntry> &desired) noexcept
{
	WallApplyPlan plan;
	try {
		if (!desired_shape_valid(desired))
			return plan; // request_invalid, empty operations

		std::vector<std::string> snapshot_uuids;
		for (const auto &entry : snapshot.entries) {
			if (!ownership_source_uuid_valid(entry.source_uuid))
				return plan; // request_invalid
			if (std::find(snapshot_uuids.begin(), snapshot_uuids.end(), entry.source_uuid) !=
			    snapshot_uuids.end())
				return plan; // request_invalid
			snapshot_uuids.push_back(entry.source_uuid);
		}

		if (!ownership_ledger_consistent(ledger)) {
			plan.status = WallApplyPlanStatus::ledger_invalid;
			return plan;
		}

		const auto bindings = classify_wall_entries(ledger, snapshot_uuids);
		std::map<std::string, std::string> uuid_to_ledger_camera;
		for (const auto &entry : ledger)
			uuid_to_ledger_camera.emplace(entry.source_uuid, entry.camera_id);

		std::vector<std::pair<std::string, std::string>> current; // camera, uuid in snapshot order
		for (std::size_t i = 0; i < bindings.size(); ++i) {
			if (!bindings[i].camera_id) {
				plan.status = WallApplyPlanStatus::graph_unbound;
				plan.operations.clear();
				plan.rollback.clear();
				return plan;
			}
			current.emplace_back(*bindings[i].camera_id, snapshot_uuids[i]);
		}

		// A desired UUID may not be claimed by a different camera anywhere in
		// the ledger (exact equality only; names/URLs are never consulted).
		for (const auto &entry : desired) {
			const auto claim = uuid_to_ledger_camera.find(entry.source_uuid);
			if (claim != uuid_to_ledger_camera.end() && claim->second != entry.camera_id)
				return plan; // request_invalid
		}

		std::map<std::string, std::string> desired_by_camera;
		for (const auto &entry : desired)
			desired_by_camera.emplace(entry.camera_id, entry.source_uuid);
		std::set<std::string> current_cameras;
		for (const auto &item : current)
			current_cameras.insert(item.first);

		std::size_t mutations = 0;
		for (const auto &[camera, uuid] : current) {
			const auto want = desired_by_camera.find(camera);
			if (want == desired_by_camera.end()) {
				plan.operations.push_back({WallApplyOpKind::remove, camera, uuid, std::string{}});
				++mutations;
			} else if (want->second == uuid) {
				plan.operations.push_back({WallApplyOpKind::keep, camera, uuid, std::string{}});
			} else {
				plan.operations.push_back({WallApplyOpKind::replace, camera, uuid, want->second});
				++mutations;
			}
		}
		for (const auto &entry : desired) {
			if (current_cameras.find(entry.camera_id) == current_cameras.end()) {
				plan.operations.push_back({WallApplyOpKind::add, entry.camera_id, std::string{}, entry.source_uuid});
				++mutations;
			}
		}

		// Exact inverse in reverse execution order. Bindings only: recreating a
		// removed source object needs the executor's protected settings backup.
		for (auto it = plan.operations.rbegin(); it != plan.operations.rend(); ++it) {
			switch (it->kind) {
			case WallApplyOpKind::keep:
				break;
			case WallApplyOpKind::add:
				plan.rollback.push_back({WallApplyUndoKind::drop_binding, it->camera_id, it->new_uuid});
				break;
			case WallApplyOpKind::remove:
				plan.rollback.push_back({WallApplyUndoKind::restore_binding, it->camera_id, it->old_uuid});
				break;
			case WallApplyOpKind::replace:
				plan.rollback.push_back({WallApplyUndoKind::drop_binding, it->camera_id, it->new_uuid});
				plan.rollback.push_back({WallApplyUndoKind::restore_binding, it->camera_id, it->old_uuid});
				break;
			}
		}

		plan.status = mutations == 0 ? WallApplyPlanStatus::noop : WallApplyPlanStatus::planned;
		return plan;
	} catch (...) {
		WallApplyPlan failed;
		failed.status = WallApplyPlanStatus::request_invalid;
		return failed;
	}
}
} // namespace webobs::native_host
