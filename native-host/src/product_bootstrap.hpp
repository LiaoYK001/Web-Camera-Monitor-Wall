#pragma once

#include <obs.h>

#include <array>
#include <string>

namespace webobs::native_host {
// Product-owned local monitoring configuration. Cameras are never logged and
// their URLs are only passed to the existing OBS Media Source.
struct ProductCamera {
	std::string id;
	std::string name;
	std::string url;
	bool hardware_decode = false;
};

struct ProductWallResult {
	obs_scene_t *scene = nullptr; // Owned reference; caller must release.
	std::array<obs_source_t *, 5> sources{};
	std::array<std::string, 5> uuids;
	int created = 0;
	int reused = 0;
	bool scene_reused = false;
	std::string error;

	// Releases every still-owned source and the scene reference.
	void release();
};

// Creates or reuses the five OBS Media Sources and the wall scene. Existing
// same-named sources are reused only when their media settings already match;
// otherwise the bootstrap fails without overwriting them. Newly created sources
// are removed again when a later step fails.
ProductWallResult create_product_five_camera_wall(const std::array<ProductCamera, 5> &cameras,
						 const std::string &wall_name);

// Applies the private product canvas/fps to the current portable profile.
bool apply_product_video_config(int width, int height, int fps, std::string &error);
} // namespace webobs::native_host
