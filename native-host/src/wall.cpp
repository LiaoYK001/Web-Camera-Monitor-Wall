#include "wall.hpp"
#include "layout.hpp"

#include <obs-frontend-api.h>
#include <cstring>

namespace webobs::native_host {
namespace {
struct Sources {
	std::array<obs_source_t *, 5> values{};
	~Sources()
	{
		for (auto *source : values)
			obs_source_release(source);
	}
};
} // namespace

WallResult create_five_tile_wall(const std::array<std::string, 5> &source_uuids)
{
	Sources sources;
	for (std::size_t i = 0; i < sources.values.size(); ++i) {
		if (source_uuids[i].empty())
			return {nullptr, "Select an existing Media Source for every tile."};
		auto *source = obs_get_source_by_uuid(source_uuids[i].c_str());
		sources.values[i] = source;
		if (!source || obs_source_removed(source))
			return {nullptr, "A selected source no longer exists. Refresh the list."};
		const char *id = obs_source_get_unversioned_id(source);
		if (!id || std::strcmp(id, "ffmpeg_source") != 0)
			return {nullptr, "Only existing OBS Media Sources are accepted."};
	}
	obs_video_info video{};
	if (!obs_get_video_info(&video) || video.base_width < 3 || video.base_height < 2)
		return {nullptr, "The OBS canvas is not ready."};

	std::string name = "WebOBS Native Wall";
	for (unsigned suffix = 1;; ++suffix) {
		auto *existing = obs_get_source_by_name(name.c_str());
		if (!existing)
			break;
		obs_source_release(existing);
		name = "WebOBS Native Wall " + std::to_string(suffix);
	}
	auto *scene = obs_scene_create(name.c_str());
	if (!scene)
		return {nullptr, "OBS could not create a scene."};
	const auto tiles = five_tile_layout(video.base_width, video.base_height);
	for (std::size_t i = 0; i < tiles.size(); ++i) {
		auto *item = obs_scene_add(scene, sources.values[i]);
		if (!item) {
			// Remove a partial new scene; existing scenes/sources stay untouched.
			obs_source_remove(obs_scene_get_source(scene));
			obs_scene_release(scene);
			return {nullptr, "OBS could not add all five scene items."};
		}
		const auto &tile = tiles[i];
		vec2 position{static_cast<float>(tile.x), static_cast<float>(tile.y)};
		vec2 bounds{static_cast<float>(tile.width), static_cast<float>(tile.height)};
		obs_sceneitem_set_alignment(item, OBS_ALIGN_LEFT | OBS_ALIGN_TOP);
		obs_sceneitem_set_bounds_alignment(item, 0);
		obs_sceneitem_set_bounds_type(item, OBS_BOUNDS_SCALE_INNER);
		obs_sceneitem_set_bounds(item, &bounds);
		obs_sceneitem_set_pos(item, &position);
	}
	return {scene, {}};
}

void select_wall(obs_scene_t *scene)
{
	if (!scene)
		return;
	auto *source = obs_scene_get_source(scene);
	if (obs_frontend_preview_program_mode_active())
		obs_frontend_set_current_preview_scene(source);
	else
		obs_frontend_set_current_scene(source);
	obs_frontend_save();
}
} // namespace webobs::native_host
