#include "product_bootstrap.hpp"
#include "wall.hpp"

#include <obs-frontend-api.h>
#include <util/config-file.h>

#include <cstring>

namespace webobs::native_host {
namespace {
bool starts_with(const std::string &value, const char *prefix)
{
	return value.compare(0, std::strlen(prefix), prefix) == 0;
}

bool valid_camera(const ProductCamera &camera, std::string &error)
{
	if (camera.id.empty() || camera.id.size() > 64)
		return error = "camera-id-invalid", false;
	for (const char c : camera.id)
		if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' ||
		      c == '_' || c == '.'))
			return error = "camera-id-invalid", false;
	if (camera.name.empty() || camera.name.size() > 128 || camera.name.find_first_of("\r\n") != std::string::npos)
		return error = "camera-name-invalid", false;
	if (camera.url.empty() || camera.url.size() > 2048)
		return error = "camera-url-invalid", false;
	if (!starts_with(camera.url, "rtsp://") && !starts_with(camera.url, "rtsps://") &&
	    !starts_with(camera.url, "http://") && !starts_with(camera.url, "https://"))
		return error = "camera-url-invalid", false;
	return true;
}

bool media_settings_match(obs_source_t *source, const ProductCamera &camera)
{
	if (std::strcmp(obs_source_get_unversioned_id(source), "ffmpeg_source") != 0 || obs_source_removed(source))
		return false;
	auto *settings = obs_source_get_settings(source);
	if (!settings)
		return false;
	const bool local = obs_data_get_bool(settings, "is_local_file");
	const char *input = obs_data_get_string(settings, "input");
	const bool hardware = obs_data_get_bool(settings, "hw_decode");
	const bool match = !local && input && camera.url == input && hardware == camera.hardware_decode;
	obs_data_release(settings);
	return match;
}

obs_source_t *create_camera_source(const ProductCamera &camera)
{
	auto *settings = obs_data_create();
	obs_data_set_bool(settings, "is_local_file", false);
	obs_data_set_string(settings, "input", camera.url.c_str());
	obs_data_set_bool(settings, "looping", false);
	obs_data_set_bool(settings, "hw_decode", camera.hardware_decode);
	obs_data_set_bool(settings, "restart_on_activate", true);
	obs_data_set_bool(settings, "close_when_inactive", false);
	obs_data_set_int(settings, "reconnect_delay_sec", 10);
	obs_data_set_int(settings, "buffering_mb", 2);
	auto *source = obs_source_create("ffmpeg_source", camera.name.c_str(), settings, nullptr);
	obs_data_release(settings);
	return source;
}

void remove_created(const std::array<obs_source_t *, 5> &sources, const std::array<bool, 5> &created_here)
{
	// Reused and new sources can occupy any slots. Counts are reporting only,
	// never ownership: only remove objects created by this bootstrap attempt.
	// ProductWallResult::release then releases every acquired reference once.
	for (std::size_t i = 0; i < sources.size(); ++i)
		if (created_here[i] && sources[i])
			obs_source_remove(sources[i]);
}
} // namespace

void ProductWallResult::release()
{
	if (scene) {
		obs_scene_release(scene);
		scene = nullptr;
	}
	for (auto &source : sources) {
		if (source) {
			obs_source_release(source);
			source = nullptr;
		}
	}
}

ProductWallResult create_product_five_camera_wall(const std::array<ProductCamera, 5> &cameras,
						 const std::string &wall_name)
{
	ProductWallResult result;
	std::array<bool, 5> created_here{};
	for (const auto &camera : cameras)
		if (!valid_camera(camera, result.error))
			return result;
	for (std::size_t i = 0; i < cameras.size(); ++i) {
		auto *existing = obs_get_source_by_name(cameras[i].name.c_str());
		if (existing) {
			if (!media_settings_match(existing, cameras[i])) {
				obs_source_release(existing);
				remove_created(result.sources, created_here);
				result.release();
				result.error = "camera-name-conflict";
				return result;
			}
			result.sources[i] = existing;
			++result.reused;
			continue;
		}
		auto *created = create_camera_source(cameras[i]);
		if (!created) {
			remove_created(result.sources, created_here);
			result.release();
			result.error = "camera-source-create-failed";
			return result;
		}
		result.sources[i] = created;
		created_here[i] = true;
		++result.created;
	}
	std::array<std::string, 5> uuids;
	for (std::size_t i = 0; i < cameras.size(); ++i)
		uuids[i] = obs_source_get_uuid(result.sources[i]);
	auto wall = ensure_five_tile_wall(uuids, wall_name);
	if (!wall.scene) {
		remove_created(result.sources, created_here);
		result.release();
		result.error = wall.error.empty() ? "wall-unavailable" : wall.error;
		return result;
	}
	result.scene = wall.scene;
	result.scene_reused = wall.reused;
	result.uuids = uuids;
	return result;
}

bool apply_product_video_config(int width, int height, int fps, std::string &error)
{
	if (width < 320 || width > 3840 || height < 180 || height > 2160 || fps < 1 || fps > 120) {
		error = "video-config-out-of-range";
		return false;
	}
	auto *config = obs_frontend_get_profile_config();
	if (!config) {
		error = "video-profile-unavailable";
		return false;
	}
	config_set_uint(config, "Video", "BaseCX", unsigned(width));
	config_set_uint(config, "Video", "BaseCY", unsigned(height));
	config_set_uint(config, "Video", "OutputCX", unsigned(width));
	config_set_uint(config, "Video", "OutputCY", unsigned(height));
	config_set_uint(config, "Video", "FPSType", 0);
	config_set_string(config, "Video", "FPSCommon", std::to_string(fps).c_str());
	obs_frontend_reset_video();
	obs_video_info info{};
	if (!obs_get_video_info(&info) || int(info.base_width) != width || int(info.base_height) != height) {
		error = "video-config-not-applied";
		return false;
	}
	return true;
}
} // namespace webobs::native_host
