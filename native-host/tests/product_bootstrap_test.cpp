// Executable API-double contract for the actual product_bootstrap.cpp, compiled
// with the pinned OBS declarations. This does not decode/render or qualify OBS.
#include "product_bootstrap.hpp"
#include "wall.hpp"
#include <obs-frontend-api.h>
#include <util/config-file.h>

#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

static_assert(LIBOBS_API_VER == MAKE_SEMANTIC_VERSION(32, 1, 2), "OBS headers must match the product pin");

struct SettingsValues {
	std::map<std::string, bool> booleans;
	std::map<std::string, long long> integers;
	std::map<std::string, std::string> strings;
};
struct obs_data {
	SettingsValues values;
	int refs = 0, acquired = 0, released = 0;
};
struct obs_source {
	std::string name, uuid, id = "ffmpeg_source";
	obs_data_t *settings = nullptr;
	bool created = false, removed = false;
	int refs = 0, acquired = 0, released = 0, removals = 0;
};
struct obs_scene {
	int refs = 0, acquired = 0, released = 0;
};
struct config_data {};

namespace {
using webobs::native_host::ProductCamera;
using webobs::native_host::ProductWallResult;
using Cameras = std::array<ProductCamera, 5>;

void require(bool condition, const std::string &message)
{
	if (!condition)
		throw std::runtime_error(message);
}

// The owners never move their pointees, even as creation grows these vectors.
// refs count only API-owned references, not this fixture's storage ownership.
std::vector<std::unique_ptr<obs_source_t>> sources;
std::vector<std::unique_ptr<obs_data_t>> settings;
std::vector<std::unique_ptr<obs_scene_t>> scenes;
Cameras cameras;
std::array<obs_source_t *, 5> existing{};
std::array<obs_source_t *, 5> resolved{};
std::array<std::string, 5> wall_uuids{};
std::string wall_name;
int fail_create_slot = -1;
bool fail_wall = false, reuse_wall = false;
std::string wall_error;
int lookups = 0, create_attempts = 0, settings_creates = 0, settings_writes = 0, wall_calls = 0;
int selections = 0, saves = 0, profile_queries = 0, config_writes = 0, video_resets = 0, video_queries = 0;
config_t profile;

obs_data_t *store_settings(const SettingsValues &values)
{
	auto data = std::make_unique<obs_data_t>();
	data->values = values;
	auto *result = data.get();
	settings.push_back(std::move(data));
	return result;
}

SettingsValues matching_settings(const ProductCamera &camera)
{
	SettingsValues values;
	values.booleans = {{"is_local_file", false}, {"hw_decode", camera.hardware_decode}};
	values.strings = {{"input", camera.url}};
	return values;
}

obs_source_t *store_source(std::size_t slot, bool created, const SettingsValues &values)
{
	auto source = std::make_unique<obs_source_t>();
	source->name = cameras[slot].name;
	source->uuid = "fixture-uuid-" + std::to_string(slot);
	source->created = created;
	source->settings = store_settings(values);
	auto *result = source.get();
	sources.push_back(std::move(source));
	return result;
}

void reset(unsigned reuse_mask = 0)
{
	sources.clear();
	settings.clear();
	scenes.clear();
	existing.fill(nullptr);
	resolved.fill(nullptr);
	wall_uuids.fill({});
	wall_name.clear();
	fail_create_slot = -1;
	fail_wall = reuse_wall = false;
	wall_error = "fixture-wall-failure";
	lookups = create_attempts = settings_creates = settings_writes = wall_calls = 0;
	selections = saves = profile_queries = config_writes = video_resets = video_queries = 0;
	for (std::size_t i = 0; i < cameras.size(); ++i) {
		cameras[i] = {"camera-" + std::to_string(i), "Fixture camera " + std::to_string(i),
			      "rtsp://fixture.invalid/camera-" + std::to_string(i), i % 2 != 0};
		if ((reuse_mask & (1u << i)) != 0)
			existing[i] = store_source(i, false, matching_settings(cameras[i]));
	}
}

void require_no_frontend_mutation()
{
	require(selections == 0 && saves == 0, "bootstrap selected or saved a scene");
	require(profile_queries == 0 && config_writes == 0 && video_resets == 0 && video_queries == 0,
		"bootstrap accessed or changed video/profile configuration");
}

void require_balanced()
{
	for (const auto &source : sources) {
		require(source->refs == 0, "source reference leaked or over-released");
		require(source->acquired == source->released, "source acquisition/release totals differ");
	}
	for (const auto &data : settings) {
		require(data->refs == 0, "settings reference leaked or over-released");
		require(data->acquired == data->released, "settings acquisition/release totals differ");
	}
	for (const auto &scene : scenes) {
		require(scene->refs == 0 && scene->acquired == scene->released, "scene references are not balanced");
	}
}

int releases()
{
	int total = 0;
	for (const auto &source : sources)
		total += source->released;
	for (const auto &data : settings)
		total += data->released;
	for (const auto &scene : scenes)
		total += scene->released;
	return total;
}

void release_twice(ProductWallResult &result)
{
	result.release();
	const int before = releases();
	result.release();
	require(releases() == before, "result.release is not idempotent");
	require(result.scene == nullptr, "release retained a scene pointer");
	for (auto *source : result.sources)
		require(source == nullptr, "release retained a source pointer");
}

void require_removals(bool failed)
{
	for (const auto &source : sources) {
		if (!source->created)
			require(source->removals == 0, "borrowed/reused source was removed");
		else
			require(source->removals == (failed ? 1 : 0),
				failed ? "new source was not removed exactly once" : "successful source was removed");
	}
}

void check_failure(ProductWallResult &result, const std::string &error)
{
	const bool no_scene = result.scene == nullptr;
	bool cleared = true;
	for (auto *source : result.sources)
		cleared = cleared && source == nullptr;
	const auto actual_error = result.error;
	release_twice(result);
	require(no_scene && cleared, "failure returned owned source/scene references");
	require(actual_error == error, "unexpected failure error code");
	require_no_frontend_mutation();
	require_balanced();
	require_removals(true);
}

unsigned prefix_mask(unsigned mask, int end)
{
	return mask & ((1u << end) - 1u);
}

void conflict_case(unsigned reuse_mask, int conflict_slot, int conflict_kind = 0)
{
	reset(prefix_mask(reuse_mask, conflict_slot));
	auto *conflict = store_source(std::size_t(conflict_slot), false,
				      matching_settings(cameras[std::size_t(conflict_slot)]));
	if (conflict_kind == 0)
		conflict->settings->values.strings["input"] = "rtsp://fixture.invalid/different";
	if (conflict_kind == 1)
		conflict->id = "browser_source";
	if (conflict_kind == 2)
		conflict->removed = true;
	if (conflict_kind == 3)
		conflict->settings = nullptr;
	if (conflict_kind == 4)
		conflict->settings->values.booleans["is_local_file"] = true;
	if (conflict_kind == 5)
		conflict->settings->values.booleans["hw_decode"] = !cameras[std::size_t(conflict_slot)].hardware_decode;
	auto result = webobs::native_host::create_product_five_camera_wall(cameras, "Fixture wall");
	check_failure(result, "camera-name-conflict");
	require(wall_calls == 0 && lookups == conflict_slot + 1, "conflict did not stop before wall/later sources");
}

void source_failure_case(unsigned reuse_mask, int failure_slot)
{
	reset(prefix_mask(reuse_mask, failure_slot));
	fail_create_slot = failure_slot;
	auto result = webobs::native_host::create_product_five_camera_wall(cameras, "Fixture wall");
	check_failure(result, "camera-source-create-failed");
	require(wall_calls == 0 && lookups == failure_slot + 1, "source failure did not stop bootstrap");
}

void wall_failure_case(unsigned reuse_mask, bool empty_error = false)
{
	reset(reuse_mask);
	fail_wall = true;
	if (empty_error)
		wall_error.clear();
	auto result = webobs::native_host::create_product_five_camera_wall(cameras, "Fixture wall");
	check_failure(result, empty_error ? "wall-unavailable" : "fixture-wall-failure");
	require(wall_calls == 1 && lookups == 5, "wall failure did not resolve all cameras exactly once");
}

void success_case(unsigned reuse_mask, bool reused_scene)
{
	reset(reuse_mask);
	reuse_wall = reused_scene;
	auto result = webobs::native_host::create_product_five_camera_wall(cameras, "Fixture wall");
	require(result.error.empty() && result.scene != nullptr, "successful wall was not returned");
	require(result.scene_reused == reused_scene, "wall reuse flag was not propagated");
	require(result.scene->refs == 1, "result does not own exactly one scene reference");
	int reused = 0;
	for (std::size_t i = 0; i < cameras.size(); ++i) {
		const bool borrowed = (reuse_mask & (1u << i)) != 0;
		reused += borrowed ? 1 : 0;
		require(result.sources[i] == resolved[i], "result lost source identity or tile order");
		require(!borrowed || result.sources[i] == existing[i], "reused source identity changed");
		require(result.sources[i]->refs == 1, "result does not own exactly one camera reference");
		require(result.uuids[i] == resolved[i]->uuid && wall_uuids[i] == result.uuids[i],
			"wall/result UUID order differs from source identity");
	}
	require(result.reused == reused && result.created == 5 - reused, "incorrect source ownership counts");
	require(create_attempts == 5 - reused && wall_calls == 1 && lookups == 5, "unexpected bootstrap API calls");
	require(wall_name == "Fixture wall", "preferred wall name was not forwarded");
	release_twice(result);
	require_balanced();
	require_removals(false);
	require_no_frontend_mutation();
}

void invalid_case(int kind)
{
	reset(31u);
	// Invalidity in the last slot must be detected before any OBS operation.
	auto &camera = cameras[4];
	std::string error;
	if (kind <= 3) {
		error = "camera-id-invalid";
		if (kind == 0) camera.id.clear();
		if (kind == 1) camera.id = std::string(65, 'x');
		if (kind == 2) camera.id = "invalid/id";
		if (kind == 3) camera.id = "invalid\nid";
	} else if (kind <= 7) {
		error = "camera-name-invalid";
		if (kind == 4) camera.name.clear();
		if (kind == 5) camera.name = std::string(129, 'x');
		if (kind == 6) camera.name = "invalid\rname";
		if (kind == 7) camera.name = "invalid\nname";
	} else {
		error = "camera-url-invalid";
		if (kind == 8) camera.url.clear();
		if (kind == 9) camera.url = "https://fixture.invalid/" + std::string(2048, 'x');
		if (kind == 10) camera.url = "file://fixture.invalid/video";
		if (kind == 11) camera.url = "fixture.invalid/video";
	}
	auto result = webobs::native_host::create_product_five_camera_wall(cameras, "Fixture wall");
	check_failure(result, error);
	require(lookups == 0 && create_attempts == 0 && settings_creates == 0 && settings_writes == 0 && wall_calls == 0,
		"invalid input mutated or queried OBS state");
	require(result.created == 0 && result.reused == 0, "invalid input acquired cameras");
}
} // namespace

// Definitions intentionally use the real OBS declarations, including long long
// for obs_data_set_int and uint64_t for config_set_uint (portable to MSVC).
extern "C" {
obs_data_t *obs_data_create(void)
{
	++settings_creates;
	auto *data = store_settings({});
	data->refs = data->acquired = 1;
	return data;
}
void obs_data_release(obs_data_t *data)
{
	if (!data)
		return;
	require(data->refs > 0, "settings reference underflow");
	--data->refs;
	++data->released;
}
void obs_data_set_bool(obs_data_t *data, const char *name, bool value)
{
	++settings_writes;
	data->values.booleans[name] = value;
}
void obs_data_set_string(obs_data_t *data, const char *name, const char *value)
{
	++settings_writes;
	data->values.strings[name] = value;
}
void obs_data_set_int(obs_data_t *data, const char *name, long long value)
{
	++settings_writes;
	data->values.integers[name] = value;
}
bool obs_data_get_bool(obs_data_t *data, const char *name)
{
	const auto found = data->values.booleans.find(name);
	return found != data->values.booleans.end() && found->second;
}
const char *obs_data_get_string(obs_data_t *data, const char *name)
{
	const auto found = data->values.strings.find(name);
	return found == data->values.strings.end() ? "" : found->second.c_str();
}
obs_source_t *obs_get_source_by_name(const char *name)
{
	++lookups;
	for (const auto &source : sources)
		if (source->name == name) {
			// Deliberately expose removed sources as well to test the explicit
			// obs_source_removed guard in media_settings_match.
			++source->refs;
			++source->acquired;
			for (std::size_t i = 0; i < cameras.size(); ++i)
				if (cameras[i].name == name)
					resolved[i] = source.get();
			return source.get();
		}
	return nullptr;
}
obs_source_t *obs_source_create(const char *id, const char *name, obs_data_t *data, obs_data_t *hotkeys)
{
	++create_attempts;
	require(std::string(id) == "ffmpeg_source" && hotkeys == nullptr, "unexpected source type/hotkeys");
	std::size_t slot = cameras.size();
	for (std::size_t i = 0; i < cameras.size(); ++i)
		if (cameras[i].name == name)
			slot = i;
	require(slot < cameras.size(), "source created with an unexpected name");
	SettingsValues wanted = matching_settings(cameras[slot]);
	wanted.booleans.insert({{"looping", false}, {"restart_on_activate", true}, {"close_when_inactive", false}});
	wanted.integers = {{"reconnect_delay_sec", 10}, {"buffering_mb", 2}};
	require(data && data->refs == 1, "source creation did not borrow live settings");
	require(data->values.booleans == wanted.booleans && data->values.integers == wanted.integers &&
			data->values.strings == wanted.strings,
		"source media settings contract changed");
	if (int(slot) == fail_create_slot)
		return nullptr;
	auto *source = store_source(slot, true, data->values);
	source->refs = source->acquired = 1;
	resolved[slot] = source;
	return source;
}
obs_data_t *obs_source_get_settings(const obs_source_t *source)
{
	if (!source->settings)
		return nullptr;
	++source->settings->refs;
	++source->settings->acquired;
	return source->settings;
}
const char *obs_source_get_unversioned_id(const obs_source_t *source) { return source->id.c_str(); }
const char *obs_source_get_uuid(const obs_source_t *source) { return source->uuid.c_str(); }
bool obs_source_removed(const obs_source_t *source) { return source->removed; }
void obs_source_remove(obs_source_t *source)
{
	require(source && source->refs > 0, "source removal without an owned reference");
	++source->removals;
	source->removed = true;
}
void obs_source_release(obs_source_t *source)
{
	if (!source)
		return;
	require(source->refs > 0, "source reference underflow");
	--source->refs;
	++source->released;
}
void obs_scene_release(obs_scene_t *scene)
{
	if (!scene)
		return;
	require(scene->refs > 0, "scene reference underflow");
	--scene->refs;
	++scene->released;
}
void obs_frontend_set_current_scene(obs_source_t *) { ++selections; }
void obs_frontend_set_current_preview_scene(obs_source_t *) { ++selections; }
void obs_frontend_save(void) { ++saves; }
config_t *obs_frontend_get_profile_config(void)
{
	++profile_queries;
	return &profile;
}
void config_set_uint(config_t *, const char *, const char *, uint64_t) { ++config_writes; }
void config_set_string(config_t *, const char *, const char *, const char *) { ++config_writes; }
void obs_frontend_reset_video(void) { ++video_resets; }
bool obs_get_video_info(obs_video_info *info)
{
	++video_queries;
	*info = {};
	return false;
}
} // extern "C"

namespace webobs::native_host {
WallResolution ensure_five_tile_wall(const std::array<std::string, 5> &uuids, const std::string &preferred_name)
{
	++wall_calls;
	wall_uuids = uuids;
	wall_name = preferred_name;
	for (std::size_t i = 0; i < uuids.size(); ++i) {
		require(resolved[i] && resolved[i]->refs == 1, "wall did not receive a live camera reference");
		require(uuids[i] == resolved[i]->uuid, "wall input changed source identity/order");
	}
	if (fail_wall)
		return {nullptr, false, wall_error};
	// This seam models only the returned owned scene reference. Actual wall
	// item/source retention and rendering are covered elsewhere, not faked here.
	auto scene = std::make_unique<obs_scene_t>();
	scene->refs = scene->acquired = 1;
	auto *result = scene.get();
	scenes.push_back(std::move(scene));
	return {result, reuse_wall, {}};
}
} // namespace webobs::native_host

int main()
{
	int passed = 0, failed = 0;
	auto run = [&](const std::string &name, auto test) {
		try {
			test();
			++passed;
		} catch (const std::exception &error) {
			++failed;
			// Names/codes only: never include camera URLs or settings in diagnostics.
			std::cerr << "FAIL " << name << ": " << error.what() << '\n';
		}
	};

	// Named minimal regressions make the ownership-count/prefix bug obvious.
	run("reuse0-create1-conflict2", [] { conflict_case(1u, 2); });
	run("create0-reuse1-create2-conflict3", [] { conflict_case(2u, 3); });
	run("reuse0-create1-source-create-failure2", [] { source_failure_case(1u, 2); });
	run("interleaved-wall-failure", [] { wall_failure_case(0b10101u); });
	run("all-new-wall-rollback", [] { wall_failure_case(0u); });
	run("wall-error-fallback", [] { wall_failure_case(0b01010u, true); });

	// Every ownership pattern before every early-exit position, including
	// zero-created, all-new and alternating reused/new sources.
	for (int stop = 0; stop < 5; ++stop)
		for (unsigned mask = 0; mask < (1u << stop); ++mask) {
			const auto label = "slot-" + std::to_string(stop) + "-mask-" + std::to_string(mask);
			run("conflict-" + label, [=] { conflict_case(mask, stop); });
			run("source-create-failure-" + label, [=] { source_failure_case(mask, stop); });
		}
	for (unsigned mask = 0; mask < 32; ++mask) {
		run("wall-failure-mask-" + std::to_string(mask), [=] { wall_failure_case(mask); });
		run("success-new-wall-mask-" + std::to_string(mask), [=] { success_case(mask, false); });
		run("success-reused-wall-mask-" + std::to_string(mask), [=] { success_case(mask, true); });
	}
	for (int kind = 1; kind <= 5; ++kind)
		run("conflict-setting-kind-" + std::to_string(kind), [=] { conflict_case(0b00101u, 4, kind); });
	for (int kind = 0; kind < 12; ++kind)
		run("invalid-input-" + std::to_string(kind), [=] { invalid_case(kind); });

	std::cout << "Pinned OBS product bootstrap API contract: " << passed << " passed, " << failed << " failed\n";
	return failed == 0 ? 0 : 1;
}
