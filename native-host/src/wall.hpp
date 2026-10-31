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
// Studio mode selects Preview, never performs an implicit TAKE to Program.
void select_wall(obs_scene_t *scene);
} // namespace webobs::native_host
