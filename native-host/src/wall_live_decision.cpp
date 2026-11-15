#include "wall_live_decision.hpp"

#include <utility>

namespace webobs::native_host {

WallLiveDecision decide_wall_live_view(const WallSnapshot &snapshot,
				       const std::vector<OwnershipEntry> &ledger,
				       const WallLiveAuthorizer &authorizer) noexcept
{
	WallLiveDecision decision;
	try {
		std::vector<std::string> uuids;
		uuids.reserve(snapshot.entries.size());
		for (const WallSnapshotEntry &entry : snapshot.entries) {
			if (!ownership_source_uuid_valid(entry.source_uuid))
				return decision; // invalid_request, zero calls
			for (const std::string &seen : uuids)
				if (seen == entry.source_uuid)
					return decision; // duplicate UUID, invalid_request
			uuids.push_back(entry.source_uuid);
		}
		if (!ownership_ledger_consistent(ledger)) {
			decision.status = WallLiveDecisionStatus::ledger_invalid;
			return decision; // zero calls
		}
		const std::vector<OwnershipBinding> bindings = classify_wall_entries(ledger, uuids);
		std::vector<std::string> bound_ids;
		bound_ids.reserve(bindings.size());
		for (const OwnershipBinding &binding : bindings) {
			if (!binding.camera_id.has_value()) {
				decision.status = WallLiveDecisionStatus::graph_unbound;
				return decision; // zero calls
			}
			bound_ids.push_back(*binding.camera_id);
		}
		std::vector<std::string> accepted;
		accepted.reserve(bound_ids.size());
		for (const std::string &camera_id : bound_ids) {
			const CameraPermission permission = authorizer(camera_id);
			if (permission == CameraPermission::denied) {
				decision.status = WallLiveDecisionStatus::forbidden;
				decision.evaluated = accepted.size();
				return decision; // stop immediately; late allows ignored
			}
			if (permission == CameraPermission::unavailable) {
				decision.status = WallLiveDecisionStatus::unavailable;
				decision.evaluated = accepted.size();
				return decision;
			}
			accepted.push_back(camera_id);
		}
		decision.status = WallLiveDecisionStatus::allowed;
		decision.evaluated = accepted.size();
		decision.bound_camera_ids = std::move(accepted);
		return decision;
	} catch (...) {
		decision.bound_camera_ids.clear();
		decision.status = WallLiveDecisionStatus::unavailable;
		return decision;
	}
}
} // namespace webobs::native_host
