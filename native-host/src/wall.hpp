#pragma once

#include <obs.h>
#include <array>
#include <string>

namespace webobs::native_host {
struct WallResult {
	// Owned reference; caller must release with obs_scene_release.
	obs_scene_t *scene = nullptr;
	std::string error;
};

// Only existing ffmpeg_source UUIDs are accepted. No source/decoder is created,
// settings are not changed and existing scenes are never overwritten.
WallResult create_five_tile_wall(const std::array<std::string, 5> &source_uuids);
// Reuse an existing wall scene with exactly these five sources in tile order;
// create it only when no scene with the preferred name exists. A same-named
// scene with different items is an error (never overwritten).
struct WallResolution {
	obs_scene_t *scene = nullptr; // Owned reference; caller must release.
	bool reused = false;
	std::string error;
};
WallResolution ensure_five_tile_wall(const std::array<std::string, 5> &source_uuids,
				     const std::string &preferred_name);
// Studio mode selects Preview, never performs an implicit TAKE to Program.
void select_wall(obs_scene_t *scene);
} // namespace webobs::native_host
