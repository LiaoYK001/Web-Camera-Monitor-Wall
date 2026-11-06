#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace webobs::native_host {
enum class WallSnapshotStatus { success, invalid_request, unavailable, unsupported };

struct WallSnapshotEntry {
	std::int64_t item_id = 0;
	std::string source_uuid;
	bool visible = false; // OBS user-visible flag, not rendered pixels/transition state.
};

struct WallSnapshot {
	std::string scene_uuid;
	// OBS scene enumeration order, including hidden items; not layout/tile order.
	std::array<WallSnapshotEntry, 5> entries;
};

struct WallSnapshotResult {
	WallSnapshotStatus status = WallSnapshotStatus::unavailable;
	// Present only on success. Failures expose no partial entries or raw data.
	std::optional<WallSnapshot> snapshot;
};

// Internal/unexposed read-only observation of an existing flat five-item scene.
// UUID syntax is exactly lowercase ASCII 8-4-4-4-12 hex, without normalization.
// The caller must run in the appropriate OBS frontend/control context and
// serialize against scene-collection, source-removal and filter/graph edits.
// The scene's recursive audio/video locks cover enumeration, NOT the whole OBS
// graph or later use. This is a TOCTOU-prone observation, not identity binding,
// authorization, a revision/generation, or a registry grant. No names, settings,
// URLs, raw pointers or frontend state are read or returned. No graph is changed.
// Transitions/other media dependencies are not audited. Lock acquisition and
// filter traversal are untimed; this does not provide a hard operation deadline.
WallSnapshotResult inspect_existing_wall(std::string_view scene_uuid) noexcept;
} // namespace webobs::native_host
