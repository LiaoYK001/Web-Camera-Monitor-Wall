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
struct ItemCheck {
	const std::array<std::string, 5> *uuids;
	std::size_t index = 0;
	bool ok = true;
};

bool scene_item_uuids_match(obs_scene_t *scene, const std::array<std::string, 5> &uuids)
{
	ItemCheck check{&uuids};
	obs_scene_enum_items(
		scene,
		[](obs_scene_t *, obs_sceneitem_t *item, void *opaque) {
			auto *state = static_cast<ItemCheck *>(opaque);
			if (state->index >= state->uuids->size()) {
				state->ok = false;
				return false;
			}
			auto *source = obs_sceneitem_get_source(item);
			const char *uuid = source ? obs_source_get_uuid(source) : nullptr;
			if (!uuid || (*state->uuids)[state->index] != uuid) {
				state->ok = false;
				return false;
			}
			++state->index;
			return true;
		},
		&check);
	return check.ok && check.index == uuids.size();
}

struct SceneScan {
	const std::array<std::string, 5> *uuids;
	const std::string *name;
	bool name_taken = false;
	obs_scene_t *matched = nullptr;
};

bool scan_scenes(void *opaque, obs_source_t *source)
{
	auto *scan = static_cast<SceneScan *>(opaque);
	if (std::strcmp(obs_source_get_name(source), scan->name->c_str()) != 0)
		return true;
	scan->name_taken = true;
	auto *scene = obs_scene_from_source(source);
	if (!scene || !scene_item_uuids_match(scene, *scan->uuids))
		return true;
	obs_source_get_ref(source);
	scan->matched = scene;
	return false;
}
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

WallResolution ensure_five_tile_wall(const std::array<std::string, 5> &source_uuids,
				     const std::string &preferred_name)
{
	for (const auto &uuid : source_uuids) {
		if (uuid.empty())
			return {nullptr, false, "Select an existing Media Source for every tile."};
	}
	SceneScan scan{&source_uuids, &preferred_name};
	obs_enum_scenes(scan_scenes, &scan);
	if (scan.matched) {
		select_wall(scan.matched);
		return {scan.matched, true, {}};
	}
	if (scan.name_taken)
		return {nullptr, false, "An existing scene has the preferred name but different sources."};
	auto created = create_five_tile_wall(source_uuids);
	if (!created.scene)
		return {nullptr, false, created.error};
	select_wall(created.scene);
	return {created.scene, false, {}};
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
