#include "product_scene.hpp"
#include "webobs/obs_scene_items.hpp"

#include <algorithm>
#include <atomic>
#include <map>
#include <tuple>

namespace webobs::native_host {
namespace {
using Data = std::unique_ptr<obs_data_t, decltype(&obs_data_release)>;
std::string settings_json(obs_source_t *source)
{
	Data settings(obs_source_get_settings(source), &obs_data_release);
	const char *json = settings ? obs_data_get_json(settings.get()) : nullptr;
	return json ? json : "";
}
using FilterState = std::tuple<std::string, std::string, std::string, bool>;
std::vector<FilterState> filters_state(obs_source_t *source)
{
	std::vector<FilterState> result;
	obs_source_enum_filters(source, [](obs_source_t *, obs_source_t *filter, void *context) {
		static_cast<std::vector<FilterState> *>(context)->emplace_back(obs_source_get_uuid(filter),
			obs_source_get_unversioned_id(filter), settings_json(filter), obs_source_enabled(filter));
	}, &result);
	return result;
}
obs_monitoring_type monitoring(const SceneSource &source)
{
	if (source.monitoring == "monitor-only") return OBS_MONITORING_TYPE_MONITOR_ONLY;
	if (source.monitoring == "monitor-and-output") return OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT;
	return OBS_MONITORING_TYPE_NONE;
}
bool same_camera(const ProductCamera &a, const ProductCamera &b)
{
	return a.id == b.id && a.profile_id == b.profile_id && a.url == b.url &&
		a.transport == b.transport && a.hardware_decode == b.hardware_decode;
}
bool valid_owner(const std::string &owner)
{
	return owner.size() == 32 && std::all_of(owner.begin(), owner.end(), [](char c) {
		return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
	});
}
} // namespace

struct ProductSceneSource {
	obs_source_t *source = nullptr;
	SceneSource configuration;
	ProductCamera camera;
	std::string settings;
	std::vector<FilterState> filters;
	bool intact() const
	{
		return source && !obs_source_removed(source) && settings_json(source) == settings &&
			filters_state(source) == filters && obs_source_muted(source) == configuration.muted &&
			obs_source_get_volume(source) == float(configuration.volume) &&
			obs_source_get_sync_offset(source) == std::int64_t(configuration.sync_offset_ms) * 1000000 &&
			obs_source_get_audio_mixers(source) == (1u << (configuration.audio_track - 1)) &&
			obs_source_get_monitoring_type(source) == monitoring(configuration);
	}
	~ProductSceneSource()
	{
		if (!source) return;
		// OBS/frontend can retain deferred references after our last graph. Strip
		// the private endpoint before removing the owned source in that case too.
		Data empty(obs_data_create(), &obs_data_release);
		obs_data_set_bool(empty.get(), "is_local_file", false);
		obs_data_set_string(empty.get(), "input", "");
		obs_data_set_string(empty.get(), "local_file", "");
		obs_source_update(source, empty.get());
		obs_source_remove(source);
		obs_source_release(source);
	}
};

std::shared_ptr<ProductSceneSource> ProductSourcePool::acquire(const std::string &owner,
	const SceneSource &configuration, const ProductCamera &camera, std::string &error)
{
	std::erase_if(entries_, [](const auto &entry) { return entry.expired(); });
	if (!valid_owner(owner) || (!entries_.empty() && owner_ != owner)) {
		error = "scene-owner-mismatch";
		return {};
	}
	owner_ = owner;
	auto key = configuration;
	key.id.clear();
	key.name.clear();
	for (auto &weak : entries_) {
		auto entry = weak.lock();
		if (entry && entry->configuration == key && same_camera(entry->camera, camera)) {
			if (!entry->intact()) {
				error = "scene-source-modified";
				return {};
			}
			return entry;
		}
	}
	if (entries_.size() >= 256) {
		error = "scene-live-source-limit";
		return {};
	}
	auto entry = std::make_shared<ProductSceneSource>();
	entry->configuration = key;
	entry->camera = camera;
	entry->source = create_product_camera_source(camera, configuration.shutdown_when_hidden,
		configuration.restart_when_active);
	if (!entry->source) {
		error = "scene-source-create-failed";
		return {};
	}
	obs_source_set_muted(entry->source, configuration.muted);
	obs_source_set_volume(entry->source, float(configuration.volume));
	obs_source_set_sync_offset(entry->source, std::int64_t(configuration.sync_offset_ms) * 1000000);
	obs_source_set_audio_mixers(entry->source, 1u << (configuration.audio_track - 1));
	obs_source_set_monitoring_type(entry->source, monitoring(configuration));
	if (!attach_obs_source_filters(entry->source, configuration, camera.name)) {
		error = "scene-filter-create-failed";
		return {};
	}
	entry->settings = settings_json(entry->source);
	entry->filters = filters_state(entry->source);
	entries_.push_back(entry);
	return entry;
}

ProductSceneGraph::~ProductSceneGraph()
{
	if (scene) {
		obs_scene_enum_items(scene, [](obs_scene_t *, obs_sceneitem_t *item, void *) {
			obs_sceneitem_set_visible(item, false);
			obs_sceneitem_remove(item);
			return true;
		}, nullptr);
		obs_source_remove(obs_scene_get_source(scene));
		obs_scene_release(scene);
	}
	// Source destruction occurs only when no other graph uses the same entry.
	sources_.clear();
}

std::unique_ptr<ProductSceneGraph> create_product_scene(ProductSourcePool &pool,
	const std::string &owner, const SceneDocument &document,
	const std::vector<ProductCamera> &bindings, std::string &error)
{
	error.clear();
	if (!valid_owner(owner) || validate_scene_document(document).has_value() ||
	    document.sources.empty() || bindings.size() != document.sources.size() ||
	    document.canvas.background_color != "#000000") {
		error = "scene-document-invalid";
		return {};
	}
	// Whole-document preflight precedes scene/source creation, including the
	// final binding. Never accept a raw URL or a partially resolved camera set.
	obs_video_info video{};
	if (!obs_get_video_info(&video) || video.base_width != unsigned(document.canvas.width) ||
	    video.base_height != unsigned(document.canvas.height)) {
		error = "scene-canvas-not-applied";
		return {};
	}
	std::map<std::pair<std::string, std::string>, const ProductCamera *> resolved;
	for (std::size_t i = 0; i < document.sources.size(); ++i) {
		const auto &source = document.sources[i];
		const auto &camera = bindings[i];
		if (source.kind != "camera" || source.camera_id != camera.id ||
		    source.profile_id != camera.profile_id || source.transport != camera.transport ||
		    source.hardware_decode != (camera.hardware_decode.has_value() ?
			(*camera.hardware_decode ? "on" : "off") : "auto") || !valid_product_camera(camera, error)) {
			error = "scene-camera-binding-invalid";
			return {};
		}
		const auto [existing, inserted] = resolved.emplace(std::make_pair(camera.id, camera.profile_id), &camera);
		if (!inserted && !same_camera(*existing->second, camera)) {
			error = "scene-camera-binding-conflict";
			return {};
		}
		if (!source.audio_inputs.empty() || source.audio_inputs_explicit ||
		    std::any_of(source.filters.begin(), source.filters.end(), [](const auto &filter) {
			return filter.kind == "lut" || filter.kind == "mask-blend";
		    })) {
			error = "scene-routing-or-asset-unresolved";
			return {};
		}
	}
	auto graph = std::make_unique<ProductSceneGraph>();
	std::map<std::string, obs_source_t *> by_id;
	for (std::size_t i = 0; i < document.sources.size(); ++i) {
		auto entry = pool.acquire(owner, document.sources[i], bindings[i], error);
		if (!entry) return {};
		by_id.emplace(document.sources[i].id, entry->source);
		graph->uuids.emplace_back(obs_source_get_uuid(entry->source));
		graph->sources_.push_back(std::move(entry));
	}
	static std::atomic_uint64_t sequence = 0;
	const auto name = "WebOBS scene " + document.id + " " + std::to_string(sequence.fetch_add(1));
	graph->scene = obs_scene_create(name.c_str());
	if (!graph->scene) {
		error = "scene-create-failed";
		return {};
	}
	std::vector<const SceneItem *> ordered;
	for (const auto &item : document.items) ordered.push_back(&item);
	std::sort(ordered.begin(), ordered.end(), [](const auto *a, const auto *b) { return a->z_index < b->z_index; });
	for (const auto *item : ordered) {
		if (!add_obs_scene_item(graph->scene, by_id.at(item->source_id), *item)) {
			error = "scene-item-create-failed";
			return {};
		}
	}
	return graph;
}
} // namespace webobs::native_host
