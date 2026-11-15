#pragma once
#include <obs.h>
#include <optional>
#include <string>

namespace webobs::native_host {
// Product-owned local monitoring configuration. Cameras are never logged and
// their URLs are only passed to the existing OBS Media Source.
struct ProductCamera {
	std::string id;
	std::string name;
	std::string url;
	// Unspecified: preserve a reused source, prefer OBS hardware decoding for a
	// new source. Explicit false/true remain strict source compatibility settings.
	std::optional<bool> hardware_decode;
	std::string transport = "auto";
	std::string profile_id = "main";
};

// No authority is granted here. The caller must bind the camera/profile and
// authorize it before creating a source; errors never contain input URLs.
bool valid_product_camera(const ProductCamera &camera, std::string &error);
obs_source_t *create_product_camera_source(const ProductCamera &camera, bool close_when_inactive,
	bool restart_when_active = true);
} // namespace webobs::native_host
