#include "camera_catalog_binding.hpp"

#include "wall_apply_authorization.hpp"

#include <map>

namespace webobs::native_host {
namespace {
constexpr std::size_t kMaxCatalogCameras = 256;
} // namespace

CameraCatalogBinding classify_camera_catalog(const std::vector<OwnershipEntry> &ledger,
					     const std::vector<CameraCatalogEntry> &catalog) noexcept
{
	CameraCatalogBinding binding;
	try {
		if (catalog.size() > kMaxCatalogCameras)
			return binding;
		std::map<std::string, bool> enabled_by_id;
		for (const auto &entry : catalog) {
			if (!ownership_camera_id_valid(entry.camera_id))
				return binding;
			if (!enabled_by_id.emplace(entry.camera_id, entry.enabled).second)
				return binding;
		}
		if (!ownership_ledger_consistent(ledger))
			return binding;
		for (const auto &entry : ledger) {
			++binding.entries_checked;
			const auto found = enabled_by_id.find(entry.camera_id);
			if (found == enabled_by_id.end()) {
				binding.status = CameraCatalogStatus::unknown_camera;
				return binding;
			}
			if (!found->second) {
				binding.status = CameraCatalogStatus::disabled_camera;
				return binding;
			}
		}
		binding.status = CameraCatalogStatus::bound;
		return binding;
	} catch (...) {
		CameraCatalogBinding failed;
		return failed;
	}
}

WallApplyAuthorization authorize_wall_apply_with_catalog(
	const std::vector<CameraCatalogEntry> &catalog, SessionStore &sessions, std::string_view session_token,
	std::string_view wall_resource_id, const std::vector<OwnershipEntry> &ledger,
	const std::vector<WallApplyEntry> &desired, const std::function<std::optional<WallSnapshot>()> &provider,
	const NativeAuthorizationBackend &backend, std::chrono::milliseconds total_budget,
	NativeOperationClock now) noexcept
{
	WallApplyAuthorization result;
	try {
		const CameraCatalogBinding binding = classify_camera_catalog(ledger, catalog);
		switch (binding.status) {
		case CameraCatalogStatus::bound:
			break;
		case CameraCatalogStatus::invalid_catalog:
			result.status = WallApplyAuthorizationStatus::invalid_request;
			return result;
		case CameraCatalogStatus::unknown_camera:
			result.status = WallApplyAuthorizationStatus::graph_unbound;
			return result;
		case CameraCatalogStatus::disabled_camera:
			result.status = WallApplyAuthorizationStatus::forbidden;
			return result;
		}
		return authorize_wall_apply(sessions, session_token, wall_resource_id, ledger, desired, provider, backend,
					     total_budget, std::move(now));
	} catch (...) {
		WallApplyAuthorization failed;
		failed.status = WallApplyAuthorizationStatus::unavailable;
		return failed;
	}
}

} // namespace webobs::native_host
