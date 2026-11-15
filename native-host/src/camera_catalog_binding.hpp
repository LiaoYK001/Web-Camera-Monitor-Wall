#pragma once

#include "source_ownership.hpp"

#include <cstddef>
#include <string>
#include <vector>

namespace webobs::native_host {

// Authoritative camera catalog observation supplied by a trusted account/registry
// adapter. This module trusts the adapter only for the facts it passes in: a
// camera exists under this exact id and is currently enabled. It never reads the
// registry database, HTTP, OBS or files itself.
struct CameraCatalogEntry {
	std::string camera_id;
	bool enabled = false;
};

enum class CameraCatalogStatus {
	bound,           // every ledger claim maps to an enabled catalog camera
	unknown_camera,  // a ledger claim names a camera the catalog does not know
	disabled_camera, // a ledger claim names a catalog camera that is disabled
	invalid_catalog, // catalog shape or ledger consistency violated
};

struct CameraCatalogBinding {
	CameraCatalogStatus status = CameraCatalogStatus::invalid_catalog;
	std::size_t entries_checked = 0; // ledger entries examined before stopping
};

// Fail-closed rules (pure, no I/O):
//  1. the catalog must contain at most 256 entries, every id must match the
//     cluster identifier syntax and no id may repeat;
//  2. the ledger must pass ownership_ledger_consistent;
//  3. ledger entries are examined in order: the first unknown camera yields
//     `unknown_camera`, the first disabled camera yields `disabled_camera`;
//     an empty ledger is trivially `bound` (other gates handle the wall shape).
// The result proves only "these claimed identities exist and are enabled in
// the injected observation"; it is not an authorization grant and not a
// revision/epoch binding: the adapter must supply a fresh observation.
[[nodiscard]] CameraCatalogBinding classify_camera_catalog(const std::vector<OwnershipEntry> &ledger,
							   const std::vector<CameraCatalogEntry> &catalog) noexcept;

} // namespace webobs::native_host
