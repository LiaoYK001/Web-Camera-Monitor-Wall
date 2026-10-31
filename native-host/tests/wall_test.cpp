// Contract test against actual pinned OBS headers. Fake API functions below
// record scene operations; they do NOT decode, render or qualify hardware.
#include "wall.hpp"
#include "layout.hpp"
#include <obs-frontend-api.h>

#include <cassert>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

static_assert(LIBOBS_API_VER == MAKE_SEMANTIC_VERSION(32, 1, 2), "OBS headers must match the product pin");

struct obs_source {
	std::string uuid, name, id = "ffmpeg_source";
	int refs = 0;
	bool removed = false;
};
struct obs_scene_item {
	obs_source_t *source{};
	vec2 pos{}, bounds{};
	uint32_t alignment{}, bounds_alignment{};
	obs_bounds_type bounds_type{};
};
struct obs_scene {
	obs_source_t source;
	std::vector<obs_scene_item> items;
};
namespace {
std::vector<obs_source_t> sources;
std::vector<std::unique_ptr<obs_scene_t>> scenes;
obs_video_info video{};
bool video_ready = true, studio = false;
int fail_add = -1, created = 0, saves = 0;
obs_source_t *preview = nullptr, *program = nullptr;
void reset()
{
	sources.clear();
	scenes.clear();
	for (int i = 0; i < 5; ++i)
		sources.push_back({"uuid-" + std::to_string(i), "camera-" + std::to_string(i)});
	video = {};
	video.base_width = 1921;
	video.base_height = 1081;
	video_ready = true;
	studio = false;
	fail_add = -1;
	created = saves = 0;
	preview = program = nullptr;
}
std::array<std::string, 5> selection()
{
	return {"uuid-0", "uuid-1", "uuid-2", "uuid-3", "uuid-4"};
}
void balanced()
{
	for (const auto &source : sources)
		assert(source.refs == 0);
}
} // namespace

extern "C" {
obs_source_t *obs_get_source_by_uuid(const char *uuid)
{
	for (auto &source : sources)
		if (source.uuid == uuid) {
			++source.refs;
			return &source;
		}
	return nullptr;
}
obs_source_t *obs_get_source_by_name(const char *name)
{
	for (auto &scene : scenes)
		if (scene->source.name == name && !scene->source.removed) {
			++scene->source.refs;
			return &scene->source;
		}
	return nullptr;
}
void obs_source_release(obs_source_t *source)
{
	if (source)
		--source->refs;
}
bool obs_source_removed(const obs_source_t *source) { return source->removed; }
const char *obs_source_get_unversioned_id(const obs_source_t *source) { return source->id.c_str(); }
bool obs_get_video_info(obs_video_info *out)
{
	*out = video;
	return video_ready;
}
obs_scene_t *obs_scene_create(const char *name)
{
	auto scene = std::make_unique<obs_scene_t>();
	scene->source.name = name;
	scene->items.reserve(5);
	auto *result = scene.get();
	scenes.push_back(std::move(scene));
	++created;
	return result;
}
obs_source_t *obs_scene_get_source(const obs_scene_t *scene)
{
	return const_cast<obs_source_t *>(&scene->source);
}
obs_sceneitem_t *obs_scene_add(obs_scene_t *scene, obs_source_t *source)
{
	if (static_cast<int>(scene->items.size()) == fail_add)
		return nullptr;
	scene->items.push_back({source});
	return &scene->items.back();
}
void obs_scene_release(obs_scene_t *) {}
void obs_source_remove(obs_source_t *source) { source->removed = true; }
void obs_sceneitem_set_alignment(obs_sceneitem_t *item, uint32_t value) { item->alignment = value; }
void obs_sceneitem_set_bounds_alignment(obs_sceneitem_t *item, uint32_t value) { item->bounds_alignment = value; }
void obs_sceneitem_set_bounds_type(obs_sceneitem_t *item, obs_bounds_type value) { item->bounds_type = value; }
void obs_sceneitem_set_bounds(obs_sceneitem_t *item, const vec2 *value) { item->bounds = *value; }
void obs_sceneitem_set_pos(obs_sceneitem_t *item, const vec2 *value) { item->pos = *value; }
bool obs_frontend_preview_program_mode_active(void) { return studio; }
void obs_frontend_set_current_preview_scene(obs_source_t *scene) { preview = scene; }
void obs_frontend_set_current_scene(obs_source_t *scene) { program = scene; }
void obs_frontend_save(void) { ++saves; }
}

int main()
{
	using namespace webobs::native_host;
	reset();
	auto wall = create_five_tile_wall(selection());
	assert(wall.scene && wall.error.empty() && wall.scene->items.size() == 5);
	for (std::size_t i = 0; i < 5; ++i) {
		const auto &item = wall.scene->items[i];
		assert(item.source == &sources[i]); // Identity, not a copy/new decoder.
		assert(item.alignment == (OBS_ALIGN_LEFT | OBS_ALIGN_TOP));
		assert(item.bounds_alignment == 0 && item.bounds_type == OBS_BOUNDS_SCALE_INNER);
	}
	assert(wall.scene->items[0].bounds.x == 640 && wall.scene->items[2].bounds.x == 641);
	assert(wall.scene->items[3].pos.y == 540 && wall.scene->items[3].bounds.y == 541);
	balanced();
	select_wall(wall.scene);
	assert(program == &wall.scene->source && preview == nullptr && saves == 1);
	studio = true;
	program = nullptr;
	select_wall(wall.scene);
	assert(preview == &wall.scene->source && program == nullptr && saves == 2);
	auto next = create_five_tile_wall(selection());
	assert(next.scene && next.scene->source.name != wall.scene->source.name);
	balanced();
	reset();
	auto repeated = selection();
	repeated.fill("uuid-0");
	wall = create_five_tile_wall(repeated);
	assert(wall.scene && wall.scene->items.size() == 5);
	for (const auto &item : wall.scene->items)
		assert(item.source == &sources[0]);
	balanced();
	for (int kind = 0; kind < 4; ++kind) {
		reset();
		auto invalid = selection();
		if (kind == 0) invalid[4].clear();
		if (kind == 1) invalid[4] = "deleted-source";
		if (kind == 2) sources[4].id = "browser_source";
		if (kind == 3) sources[4].removed = true;
		wall = create_five_tile_wall(invalid);
		assert(!wall.scene && !wall.error.empty() && created == 0);
		balanced();
	}
	reset();
	video_ready = false;
	assert(!create_five_tile_wall(selection()).scene && created == 0);
	balanced();
	reset();
	video.base_width = 2;
	assert(!create_five_tile_wall(selection()).scene && created == 0);
	balanced();
	reset();
	fail_add = 3;
	wall = create_five_tile_wall(selection());
	assert(!wall.scene && created == 1 && scenes[0]->source.removed);
	assert(program == nullptr && preview == nullptr);
	balanced();
	std::cout << "Pinned OBS API: source identity/reuse, validation, rollback, layout and Preview/Program contracts passed\n";
}
