// Link this test with src/wall_snapshot.cpp ONLY, against the pinned OBS
// headers and generated obsconfig.h. No libobs binary, Qt, frontend, or other
// production TU is linked. Only the read/ref/lock API doubles below are defined:
// an accidental creation/deletion, settings, frontend or mutation call fails
// to link. These synthetic contracts do not qualify a real OBS target/runtime.
#include "wall_snapshot.hpp"
#include <obs.h>

#include <array>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

static_assert(LIBOBS_API_VER == MAKE_SEMANTIC_VERSION(32, 1, 2), "OBS headers must match the product pin");

struct obs_source {
	std::string uuid;
	std::string id = "ffmpeg_source";
	obs_source_type type = OBS_SOURCE_TYPE_INPUT;
	int refs = 1; // Fixture's owning reference, not acquired by the implementation.
	bool removed = false, null_uuid = false, null_id = false;
	bool fail_ref = false, throw_uuid = false, enabled = true;
	std::vector<obs_source_t *> filters;
};
struct obs_scene_item {
	obs_source_t *source = nullptr;
	std::int64_t id = 0;
	bool visible = true, group = false, throw_visible = false;
	int refs = 1; // Fixture scene's owning item reference.
};
struct obs_scene {
	obs_source_t *source = nullptr;
	std::vector<obs_sceneitem_t> items;
};

namespace {
using webobs::native_host::WallSnapshotResult;
using webobs::native_host::WallSnapshotStatus;
using webobs::native_host::inspect_existing_wall;
using Status = WallSnapshotStatus;
constexpr char wall_uuid[] = "a0000000-0000-4000-8000-000000000001";
constexpr std::array<const char *, 7> media_uuids{
	"b0000000-0000-4000-8000-000000000001", "b0000000-0000-4000-8000-000000000002",
	"b0000000-0000-4000-8000-000000000003", "b0000000-0000-4000-8000-000000000004",
	"b0000000-0000-4000-8000-000000000005", "b0000000-0000-4000-8000-000000000006",
	"b0000000-0000-4000-8000-000000000007"};

void require(bool condition, const char *code)
{
	if (!condition)
		throw std::runtime_error(code); // Fixed codes only, no graph/request data.
}

struct Fixture {
	obs_source_t root, filter;
	std::array<obs_source_t, 7> media;
	obs_scene_t scene;
	bool missing_lookup = false, no_scene = false, skip_atomic = false;
	bool null_item = false, throw_filters = false, throw_enum = false;
	bool remove_at_lock = false, mismatch_at_lock = false, violation = false;
	int api_calls = 0, lookup_calls = 0, atomic_calls = 0, enum_calls = 0;
	int lock_depth = 0, callbacks = 0, acquired = 0, released = 0, child_refs = 0;
	int filter_callbacks = 0;

	Fixture()
	{
		root.uuid = wall_uuid;
		root.id = "scene";
		root.type = OBS_SOURCE_TYPE_SCENE;
		filter.uuid = "c0000000-0000-4000-8000-000000000001";
		filter.id = "color_filter";
		filter.type = OBS_SOURCE_TYPE_FILTER;
		scene.source = &root;
		for (std::size_t i = 0; i < media.size(); ++i)
			media[i].uuid = media_uuids[i];
		for (std::size_t i = 0; i < 5; ++i)
			scene.items.push_back({&media[i], static_cast<std::int64_t>(90 - i * 7), i % 2 == 0});
	}
};
Fixture *current = nullptr;

void observe(bool condition) noexcept
{
	if (!condition)
		current->violation = true;
}
void balanced()
{
	require(current->root.refs == 1 && current->filter.refs == 1, "root_ref_balance");
	for (const auto &source : current->media)
		require(source.refs == 1, "media_ref_balance");
	for (const auto &item : current->scene.items)
		require(item.refs == 1, "item_ref_balance");
	require(current->acquired == current->released, "total_ref_balance");
	require(current->lock_depth == 0 && !current->violation, "locking_or_lifetime_contract");
}

void failure(const WallSnapshotResult &result, Status expected)
{
	require(result.status == expected, "failure_status");
	require(!result.snapshot.has_value(), "failure_has_no_partial_snapshot");
	balanced();
}
void success(const WallSnapshotResult &result)
{
	require(result.status == Status::success && result.snapshot.has_value(), "success_status");
	require(result.snapshot->scene_uuid == wall_uuid, "scene_uuid_copied");
	require(result.snapshot->entries.size() == 5, "exactly_five_entries");
	for (std::size_t i = 0; i < result.snapshot->entries.size(); ++i) {
		const auto &actual = result.snapshot->entries[i];
		const auto &expected = current->scene.items[i];
		require(actual.item_id == expected.id, "item_id_and_order");
		require(actual.source_uuid == expected.source->uuid, "actual_source_uuid_and_order");
		require(actual.visible == expected.visible, "hidden_visibility_preserved");
	}
	require(current->lookup_calls == 1 && current->atomic_calls == 1 && current->enum_calls == 1,
		"one_lookup_locked_enumeration");
	require(current->callbacks == 5 && current->child_refs == 5, "five_items_retained");
	balanced();
}

int cases = 0;
template<typename Change> void reject(Change change, Status expected)
{
	Fixture fixture;
	current = &fixture;
	change(fixture);
	failure(inspect_existing_wall(wall_uuid), expected);
	++cases;
}

// These guards model the pinned API's internal refs and full scene lock. They
// also prove an injected C++ exception is contained before the C callback exits.
struct LockGuard {
	obs_source_t *source;
	explicit LockGuard(obs_source_t *value) : source(value)
	{
		++source->refs;
		++current->acquired;
		++current->lock_depth;
	}
	~LockGuard()
	{
		--current->lock_depth;
		--source->refs;
		++current->released;
	}
};
struct ItemGuard {
	obs_sceneitem_t *item;
	explicit ItemGuard(obs_sceneitem_t *value) : item(value) { ++item->refs; }
	~ItemGuard() { --item->refs; }
};
} // namespace

// Declarations come from actual obs.h, so constness/callback/calling signatures
// cannot drift into a handwritten substitute OBS header. No mutation doubles.
extern "C" {
obs_source_t *obs_get_source_by_uuid(const char *uuid)
{
	++current->api_calls;
	++current->lookup_calls;
	observe(std::string_view(uuid) == wall_uuid);
	if (current->missing_lookup)
		return nullptr;
	++current->root.refs;
	++current->acquired;
	return &current->root;
}
obs_source_t *obs_source_get_ref(obs_source_t *source)
{
	++current->api_calls;
	observe(current->lock_depth == 1 && source && source->refs >= 1);
	if (!source || source->fail_ref)
		return nullptr;
	++source->refs;
	++current->acquired;
	++current->child_refs;
	return source;
}
void obs_source_release(obs_source_t *source)
{
	++current->api_calls;
	observe(source && source->refs > 1);
	if (source) {
		--source->refs;
		++current->released;
	}
}
bool obs_source_removed(const obs_source_t *source)
{
	++current->api_calls;
	observe(source && source->refs > 1);
	return source->removed;
}
const char *obs_source_get_uuid(const obs_source_t *source)
{
	++current->api_calls;
	observe(source && source->refs > 1);
	if (source->throw_uuid)
		throw std::runtime_error("injected_uuid_failure");
	return source->null_uuid ? nullptr : source->uuid.c_str();
}
const char *obs_source_get_unversioned_id(const obs_source_t *source)
{
	++current->api_calls;
	observe(source && source->refs > 1);
	return source->null_id ? nullptr : source->id.c_str();
}
enum obs_source_type obs_source_get_type(const obs_source_t *source)
{
	++current->api_calls;
	observe(source && source->refs > 1);
	return source->type;
}
obs_scene_t *obs_scene_from_source(const obs_source_t *source)
{
	++current->api_calls;
	observe(source == &current->root && source->refs > 1);
	return current->no_scene || source->id != "scene" ? nullptr : &current->scene;
}
void obs_source_enum_filters(obs_source_t *source, obs_source_enum_proc_t callback, void *param)
{
	++current->api_calls;
	observe(current->lock_depth == 1 && source->refs > 1);
	if (current->throw_filters)
		throw std::runtime_error("injected_filter_failure");
	for (auto *filter : source->filters) {
		// Intentionally NOT conditional on filter->enabled.
		++current->filter_callbacks;
		callback(source, filter, param);
	}
}
void obs_scene_atomic_update(obs_scene_t *scene, obs_scene_atomic_update_func callback, void *data)
{
	++current->api_calls;
	++current->atomic_calls;
	observe(scene == &current->scene && current->root.refs == 2 && current->lock_depth == 0);
	if (current->skip_atomic)
		return; // Models failure to get the internal scene ref in the pinned API.
	LockGuard guard(scene->source);
	if (current->remove_at_lock)
		current->root.removed = true;
	if (current->mismatch_at_lock)
		current->root.uuid = media_uuids[6];
	callback(data, scene);
}
void obs_scene_enum_items(obs_scene_t *scene, bool (*callback)(obs_scene_t *, obs_sceneitem_t *, void *), void *data)
{
	++current->api_calls;
	++current->enum_calls;
	observe(scene == &current->scene && current->lock_depth == 1 && current->root.refs == 3);
	if (current->throw_enum)
		throw std::runtime_error("injected_enumeration_failure");
	if (current->null_item) {
		++current->callbacks;
		callback(scene, nullptr, data);
		return;
	}
	for (auto &item : scene->items) {
		ItemGuard guard(&item);
		++current->callbacks;
		if (!callback(scene, &item, data))
			break;
	}
}
obs_source_t *obs_sceneitem_get_source(const obs_sceneitem_t *item)
{
	++current->api_calls;
	observe(current->lock_depth == 1 && item && item->refs == 2);
	return item->source;
}
int64_t obs_sceneitem_get_id(const obs_sceneitem_t *item)
{
	++current->api_calls;
	observe(current->lock_depth == 1 && item && item->refs == 2);
	return item->id;
}
bool obs_sceneitem_is_group(obs_sceneitem_t *item)
{
	++current->api_calls;
	observe(current->lock_depth == 1 && item && item->refs == 2);
	return item->group;
}
bool obs_sceneitem_visible(const obs_sceneitem_t *item)
{
	++current->api_calls;
	observe(current->lock_depth == 1 && item && item->refs == 2);
	if (item->throw_visible)
		throw std::runtime_error("injected_visibility_failure");
	return item->visible;
}
} // extern "C"

int main()
{
	try {
		// Only these deliberate malformed-input cases use noncanonical UUIDs;
		// every default source/filter/scene fixture identity above is canonical.
		const std::array<std::string, 14> invalid{
			"", " ", "a0000000-0000-4000-8000-00000000000", // Short.
			"a0000000-0000-4000-8000-0000000000010", // Long.
			"A0000000-0000-4000-8000-000000000001", // Uppercase.
			"g0000000-0000-4000-8000-000000000001", // Nonhex.
			"a0000000_0000-4000-8000-000000000001", // Wrong separator.
			"a0000000-0000_4000-8000-000000000001",
			"a0000000-0000-4000_8000-000000000001",
			"a0000000-0000-4000-8000_000000000001",
			"{a0000000-0000-4000-8000-000000000001}",
			" a0000000-0000-4000-8000-000000000001",
			"a0000000-0000-4000-8000-000000000001\n",
			std::string(wall_uuid, 36) + std::string(1, '\0')};
		for (const auto &uuid : invalid) {
			Fixture fixture;
			current = &fixture;
			failure(inspect_existing_wall(uuid), Status::invalid_request);
			require(fixture.api_calls == 0, "invalid_before_any_obs_call");
			++cases;
		}
		{
			Fixture fixture;
			current = &fixture;
			std::array<char, 36> unterminated{};
			std::string_view(wall_uuid).copy(unterminated.data(), unterminated.size());
			success(inspect_existing_wall(std::string_view(unterminated.data(), unterminated.size())));
			++cases; // Input need not be NUL terminated; the lookup copy must be.
		}
		{
			Fixture fixture;
			current = &fixture;
			fixture.scene.items[0].id = 0;
			fixture.scene.items[4].id = (std::numeric_limits<std::int64_t>::max)();
			auto result = inspect_existing_wall(wall_uuid);
			success(result); // Distinct sources, mixed hidden flags, unsorted IDs.
			fixture.media[0].uuid = media_uuids[6];
			require(result.snapshot->entries[0].source_uuid == media_uuids[0], "dto_owns_uuid_copy");
			++cases;
		}
		{
			Fixture fixture;
			current = &fixture;
			for (auto &item : fixture.scene.items) {
				item.source = &fixture.media[0];
				item.visible = false;
			}
			success(inspect_existing_wall(wall_uuid)); // Duplicates allowed, even all hidden.
			++cases;
		}

		reject([](Fixture &f) { f.missing_lookup = true; }, Status::unavailable);
		reject([](Fixture &f) { f.root.removed = true; }, Status::unavailable);
		reject([](Fixture &f) { f.root.uuid = media_uuids[0]; }, Status::unavailable);
		reject([](Fixture &f) { f.root.null_uuid = true; }, Status::unavailable);
		reject([](Fixture &f) { f.root.uuid = ""; }, Status::unavailable);
		reject([](Fixture &f) { f.root.type = OBS_SOURCE_TYPE_INPUT; }, Status::unsupported);
		reject([](Fixture &f) { f.root.id = "group"; }, Status::unsupported);
		reject([](Fixture &f) { f.no_scene = true; }, Status::unsupported);
		reject([](Fixture &f) { f.skip_atomic = true; }, Status::unavailable);
		reject([](Fixture &f) { f.remove_at_lock = true; }, Status::unavailable);
		reject([](Fixture &f) { f.mismatch_at_lock = true; }, Status::unavailable);
		reject([](Fixture &f) { f.null_item = true; }, Status::unsupported);
		for (std::size_t count = 0; count < 5; ++count)
			reject([count](Fixture &f) { f.scene.items.resize(count); }, Status::unsupported);

		// Every malformed-item case runs after four valid items, proving no
		// partial public DTO escapes and earlier acquired refs are released.
		reject([](Fixture &f) { f.scene.items[4].id = -1; }, Status::unsupported);
		reject([](Fixture &f) { f.scene.items[4].id = f.scene.items[0].id; }, Status::unsupported);
		reject([](Fixture &f) { f.scene.items[4].group = true; }, Status::unsupported);
		reject([](Fixture &f) { f.scene.items[4].source = nullptr; }, Status::unavailable);
		reject([](Fixture &f) { f.media[4].removed = true; }, Status::unavailable);
		reject([](Fixture &f) { f.media[4].fail_ref = true; }, Status::unavailable);
		reject([](Fixture &f) { f.media[4].id = "scene"; f.media[4].type = OBS_SOURCE_TYPE_SCENE; }, Status::unsupported);
		reject([](Fixture &f) { f.media[4].id = "group"; f.media[4].type = OBS_SOURCE_TYPE_SCENE; }, Status::unsupported);
		reject([](Fixture &f) { f.media[4].type = OBS_SOURCE_TYPE_SCENE; }, Status::unsupported);
		reject([](Fixture &f) { f.media[4].type = OBS_SOURCE_TYPE_FILTER; }, Status::unsupported);
		reject([](Fixture &f) { f.media[4].id = "image_source"; }, Status::unsupported);
		reject([](Fixture &f) { f.media[4].null_id = true; }, Status::unsupported);
		reject([](Fixture &f) { f.media[4].null_uuid = true; }, Status::unsupported);
		for (const auto &uuid : invalid) {
			// OBS returns a C string: bytes after its terminator are not part
			// of the UUID. The request string_view test above DOES reject NUL.
			if (uuid.size() == 37 && uuid.back() == '\0')
				continue;
			reject([&uuid](Fixture &f) { f.media[4].uuid = uuid; }, Status::unsupported);
			reject([&uuid](Fixture &f) { f.root.uuid = uuid; }, Status::unavailable);
		}

		for (bool enabled : {false, true}) {
			reject([enabled](Fixture &f) {
				f.filter.enabled = enabled;
				f.root.filters.push_back(&f.filter);
			}, Status::unsupported);
			reject([enabled](Fixture &f) {
				f.filter.enabled = enabled;
				f.media[4].filters.push_back(&f.filter);
			}, Status::unsupported);
		}
		for (bool hidden_sixth : {false, true}) {
			Fixture fixture;
			current = &fixture;
			fixture.scene.items.push_back({&fixture.media[5], 500, !hidden_sixth});
			fixture.scene.items.push_back({&fixture.media[6], 501, true});
			failure(inspect_existing_wall(wall_uuid), Status::unsupported);
			require(fixture.callbacks == 6 && fixture.child_refs == 5, "sixth_stops_without_source_read");
			++cases;
		}
		reject([](Fixture &f) { f.root.throw_uuid = true; }, Status::unavailable);
		reject([](Fixture &f) { f.media[4].throw_uuid = true; }, Status::unavailable);
		reject([](Fixture &f) { f.scene.items[4].throw_visible = true; }, Status::unavailable);
		reject([](Fixture &f) { f.throw_filters = true; }, Status::unavailable);
		reject([](Fixture &f) { f.throw_enum = true; }, Status::unavailable);

		std::cout << "wall_snapshot_contract_pass " << cases << '\n';
		return 0;
	} catch (const std::exception &error) {
		std::cerr << "wall_snapshot_contract_fail " << error.what() << '\n';
		return 1;
	} catch (...) {
		std::cerr << "wall_snapshot_contract_fail unknown_exception\n";
		return 1;
	}
}
