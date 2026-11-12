// Actual libobs graph/reference test. The input is an explicitly registered
// inert fixture, NOT FFmpeg, a decoder, a camera or a media qualification.
#include "product_scene.hpp"
#include <obs.h>
#include <algorithm>
#include <atomic>
#include <iostream>
#include <stdexcept>

namespace {
using namespace webobs;
using namespace webobs::native_host;
std::atomic_int created = 0, destroyed = 0;
const std::string owner(32, 'a'), other_owner(32, 'b');
const char *fixture_name(void *) { return "Inert graph ownership fixture"; }
void *fixture_create(obs_data_t *, obs_source_t *) { ++created; return new int(1); }
void fixture_destroy(void *data) { delete static_cast<int *>(data); ++destroyed; }
std::uint32_t fixture_width(void *) { return 320; }
std::uint32_t fixture_height(void *) { return 180; }
void fixture_render(void *, gs_effect_t *) {}
void require(bool value, const char *message)
{
	if (!value) throw std::runtime_error(message);
}
SceneDocument document()
{
	SceneDocument doc;
	doc.canvas.width = 320;
	doc.canvas.height = 180;
	for (int i = 0; i < 5; ++i) {
		SceneSource source;
		source.id = "source-" + std::to_string(i);
		source.name = "Fixture " + std::to_string(i);
		source.kind = "camera";
		source.camera_id = "camera-1";
		source.profile_id = "main";
		source.transport = "auto";
		doc.sources.push_back(source);
		SceneItem item;
		item.id = "item-" + std::to_string(i);
		item.source_id = source.id;
		item.x = i * 200;
		item.y = 20;
		item.width = 200;
		item.height = 160;
		item.rotation_degrees = i * 5;
		item.crop.left = i;
		item.locked = true;
		item.z_index = i;
		doc.items.push_back(item);
	}
	return doc;
}
void run()
{
	ProductSourcePool pool;
	auto doc = document();
	std::vector<ProductCamera> bindings(5, {"camera-1", "Same global name", "rtsp://fixture.invalid/private", {}});
	std::string error;
	auto invalid_bindings = bindings;
	invalid_bindings.back().profile_id = "unauthorized";
	require(!create_product_scene(pool, owner, doc, invalid_bindings, error) && created == 0,
		"late invalid binding performed partial source I/O");
	invalid_bindings = bindings;
	invalid_bindings.back().url += "-conflicting-resolution";
	require(!create_product_scene(pool, owner, doc, invalid_bindings, error) && created == 0,
		"conflicting resolution performed partial source I/O");
	auto malformed = doc;
	malformed.items.back().source_id = "missing";
	require(!create_product_scene(pool, owner, malformed, bindings, error) && created == 0,
		"invalid document created media");
	auto unsupported = doc;
	unsupported.sources.back().audio_inputs_explicit = true;
	require(!create_product_scene(pool, owner, unsupported, bindings, error) && created == 0,
		"unresolved audio routing created media");
	// A same-named non-pool object cannot be borrowed by the product renderer.
	auto *foreign = create_product_camera_source(bindings.front(), true);
	require(foreign && created == 1, "fixture input creation failed");
	const std::string foreign_uuid = obs_source_get_uuid(foreign);
	auto first = create_product_scene(pool, owner, doc, bindings, error);
	if (!first) std::cerr << "Graph fixture fixed error: " << error << '\n';
	require(first && first->scene && created == 2 && first->uuids.size() == 5, "shared graph creation failed");
	require(std::all_of(first->uuids.begin(), first->uuids.end(), [&](const auto &uuid) {
		return uuid == first->uuids.front() && uuid != foreign_uuid;
	}), "duplicate items did not share exactly one owned source");
	int count = 0;
	obs_scene_enum_items(first->scene, [](obs_scene_t *, obs_sceneitem_t *item, void *context) {
		auto &index = *static_cast<int *>(context);
		vec2 position{}, bounds{};
		obs_sceneitem_get_pos(item, &position);
		obs_sceneitem_get_bounds(item, &bounds);
		obs_sceneitem_crop crop{};
		obs_sceneitem_get_crop(item, &crop);
		require(position.x == index * 200 && position.y == 20 && bounds.x == 200 && bounds.y == 160 &&
			obs_sceneitem_get_rot(item) == index * 5 && crop.left == index && obs_sceneitem_locked(item),
			"shared scene item mapping changed");
		++index;
		return true;
	}, &count);
	require(count == 5, "shared graph lost items");
	auto second_doc = doc;
	second_doc.id = "second";
	for (auto &source : second_doc.sources) { source.id += "-renamed"; source.name += " renamed"; }
	for (auto &item : second_doc.items) item.source_id += "-renamed";
	auto second = create_product_scene(pool, owner, second_doc, bindings, error);
	require(second && created == 2 && second->uuids == first->uuids, "compatible second scene duplicated input");
	require(!create_product_scene(pool, other_owner, doc, bindings, error) && error == "scene-owner-mismatch" && created == 2,
		"live source crossed account boundary");
	const auto uuid = first->uuids.front();
	first.reset();
	obs_wait_for_destroy_queue();
	auto *retained = obs_get_source_by_uuid(uuid.c_str());
	require(retained && !obs_source_removed(retained), "releasing one graph destroyed another graph's source");
	// API refs can outlive the final graph: its private endpoint must still be
	// cleared immediately rather than waiting for frontend references to vanish.
	second.reset();
	obs_wait_for_destroy_queue();
	auto *settings = obs_source_get_settings(retained);
	require(obs_source_removed(retained) && std::string(obs_data_get_string(settings, "input")).empty(),
		"last graph left a live private endpoint");
	obs_data_release(settings);
	obs_source_release(retained);
	obs_wait_for_destroy_queue();
	require(destroyed == 1 && !obs_source_removed(foreign), "graph cleanup affected foreign source or leaked owned input");
	auto rebound = create_product_scene(pool, other_owner, doc, bindings, error);
	require(rebound && created == 3 && rebound->uuids.front() != uuid, "retired pool did not rebind safely");
	auto *modified = obs_get_source_by_uuid(rebound->uuids.front().c_str());
	obs_source_set_muted(modified, false);
	obs_source_release(modified);
	require(!create_product_scene(pool, other_owner, doc, bindings, error) && error == "scene-source-modified" && created == 3,
		"externally modified audio policy reused silently");
	rebound.reset();
	obs_wait_for_destroy_queue();
	obs_source_remove(foreign);
	obs_source_release(foreign);
	obs_wait_for_destroy_queue();
	require(created == destroyed, "inert source lifetime imbalance");
}
} // namespace

bool exercise_product_scene_graph()
{
	obs_source_info info{};
	info.id = "ffmpeg_source";
	info.type = OBS_SOURCE_TYPE_INPUT;
	info.output_flags = OBS_SOURCE_VIDEO | OBS_SOURCE_AUDIO | OBS_SOURCE_CUSTOM_DRAW;
	info.get_name = fixture_name;
	info.create = fixture_create;
	info.destroy = fixture_destroy;
	info.get_width = fixture_width;
	info.get_height = fixture_height;
	info.video_render = fixture_render;
	obs_register_source(&info);
	try {
		run();
		std::cout << "Actual libobs owned-source sharing, item mapping, account isolation and retirement passed with an inert input.\n";
		return true;
	} catch (const std::exception &exception) {
		std::cerr << "FAIL graph fixture: " << exception.what() << '\n';
		return false;
	}
}
