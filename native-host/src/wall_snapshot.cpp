#include "wall_snapshot.hpp"

#include <obs.h>
#include <algorithm>
#include <cstring>
#include <utility>

static_assert(LIBOBS_API_VER == MAKE_SEMANTIC_VERSION(32, 1, 2), "OBS headers must match the product pin");

namespace webobs::native_host {
namespace {
using Status = WallSnapshotStatus;

bool canonical_uuid(std::string_view uuid) noexcept
{
	if (uuid.size() != 36)
		return false;
	for (std::size_t i = 0; i < uuid.size(); ++i) {
		if (i == 8 || i == 13 || i == 18 || i == 23) {
			if (uuid[i] != '-')
				return false;
		} else if (!((uuid[i] >= '0' && uuid[i] <= '9') || (uuid[i] >= 'a' && uuid[i] <= 'f'))) {
			return false;
		}
	}
	return true;
}

// OBS owns these strings. Bound the scan rather than trusting arbitrary length.
bool canonical_uuid(const char *uuid) noexcept
{
	if (!uuid)
		return false;
	std::size_t length = 0;
	while (length < 37 && uuid[length] != '\0')
		++length;
	return length == 36 && canonical_uuid(std::string_view(uuid, length));
}

struct SourceRef {
	obs_source_t *value;
	explicit SourceRef(obs_source_t *source) noexcept : value(source) {}
	SourceRef(const SourceRef &) = delete;
	SourceRef &operator=(const SourceRef &) = delete;
	~SourceRef() { if (value) obs_source_release(value); }
};

void found_filter(obs_source_t *, obs_source_t *, void *opaque) noexcept
{
	*static_cast<bool *>(opaque) = true;
}

bool has_filters(obs_source_t *source)
{
	bool found = false;
	// Unlike an enabled-filter query, this includes disabled filters. The pinned
	// implementation holds filter_mutex; filter_count alone is an unlocked read.
	obs_source_enum_filters(source, found_filter, &found);
	return found;
}

struct RawEntry {
	std::int64_t item_id = 0;
	std::array<char, 37> uuid{};
	bool visible = false;
};
struct Scan {
	obs_source_t *scene_source;
	const char *scene_uuid;
	std::array<RawEntry, 5> entries{};
	std::size_t count = 0;
	Status status = Status::unavailable;
};

bool inspect_item(obs_scene_t *, obs_sceneitem_t *item, void *opaque) noexcept
{
	auto &scan = *static_cast<Scan *>(opaque);
	try {
		// The sixth callback rejects before reading/retaining its source. No
		// visibility filter is applied, so a hidden sixth item also rejects.
		if (scan.count == scan.entries.size() || !item || obs_sceneitem_is_group(item)) {
			scan.status = Status::unsupported;
			return false;
		}
		const auto id = obs_sceneitem_get_id(item);
		if (id < 0) {
			scan.status = Status::unsupported;
			return false;
		}
		for (std::size_t i = 0; i < scan.count; ++i) {
			if (scan.entries[i].item_id == id) {
				scan.status = Status::unsupported;
				return false;
			}
		}
		// The enumerator retains the item, which owns its source. Acquire an
		// explicit temporary source ref; never keep a borrowed pointer afterward.
		auto *borrowed = obs_sceneitem_get_source(item);
		SourceRef source(borrowed ? obs_source_get_ref(borrowed) : nullptr);
		if (!source.value || obs_source_removed(source.value)) {
			scan.status = Status::unavailable;
			return false;
		}
		const char *type_id = obs_source_get_unversioned_id(source.value);
		const char *uuid = obs_source_get_uuid(source.value);
		if (obs_source_get_type(source.value) != OBS_SOURCE_TYPE_INPUT || !type_id ||
		    std::strcmp(type_id, "ffmpeg_source") != 0 || !canonical_uuid(uuid) || has_filters(source.value)) {
			scan.status = Status::unsupported;
			return false;
		}
		auto &entry = scan.entries[scan.count];
		entry.item_id = id;
		std::copy_n(uuid, entry.uuid.size(), entry.uuid.begin());
		entry.visible = obs_sceneitem_visible(item);
		++scan.count;
		return true;
	} catch (...) {
		// No exception (including one from a test double) may cross OBS's C
		// callback frame, which must unlock/release its item deterministically.
		scan.status = Status::unavailable;
		return false;
	}
}

void inspect_locked(void *opaque, obs_scene_t *scene) noexcept
{
	auto &scan = *static_cast<Scan *>(opaque);
	try {
		const char *uuid = obs_source_get_uuid(scan.scene_source);
		if (obs_source_removed(scan.scene_source) || !canonical_uuid(uuid) ||
		    std::strcmp(uuid, scan.scene_uuid) != 0) {
			scan.status = Status::unavailable;
			return;
		}
		if (has_filters(scan.scene_source)) {
			scan.status = Status::unsupported;
			return;
		}
		scan.status = Status::success;
		obs_scene_enum_items(scene, inspect_item, &scan);
		if (scan.status == Status::success && scan.count != scan.entries.size())
			scan.status = Status::unsupported;
	} catch (...) {
		scan.status = Status::unavailable;
	}
}
} // namespace

WallSnapshotResult inspect_existing_wall(std::string_view scene_uuid) noexcept
{
	if (!canonical_uuid(scene_uuid))
		return {Status::invalid_request, std::nullopt};
	try {
		std::array<char, 37> lookup_uuid{};
		std::copy(scene_uuid.begin(), scene_uuid.end(), lookup_uuid.begin());
		SourceRef source(obs_get_source_by_uuid(lookup_uuid.data()));
		if (!source.value || obs_source_removed(source.value))
			return {Status::unavailable, std::nullopt};
		const char *actual_uuid = obs_source_get_uuid(source.value);
		if (!canonical_uuid(actual_uuid) || scene_uuid != actual_uuid)
			return {Status::unavailable, std::nullopt};
		if (obs_source_get_type(source.value) != OBS_SOURCE_TYPE_SCENE)
			return {Status::unsupported, std::nullopt};
		auto *scene = obs_scene_from_source(source.value); // Borrowed; source owns it.
		if (!scene)
			return {Status::unsupported, std::nullopt};
		Scan scan{source.value, lookup_uuid.data()};
		// OBS 32.1.2 retains the scene and holds recursive full audio/video
		// locks around this callback. Despite its name, this call need not mutate.
		obs_scene_atomic_update(scene, inspect_locked, &scan);
		if (scan.status != Status::success)
			return {scan.status, std::nullopt};
		WallSnapshot snapshot;
		snapshot.scene_uuid.assign(scene_uuid);
		for (std::size_t i = 0; i < scan.entries.size(); ++i) {
			snapshot.entries[i] = {scan.entries[i].item_id, scan.entries[i].uuid.data(), scan.entries[i].visible};
		}
		return {Status::success, std::move(snapshot)};
	} catch (...) {
		return {Status::unavailable, std::nullopt};
	}
}
} // namespace webobs::native_host
