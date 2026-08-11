#include "webobs/obs_scene_runtime.hpp"

#include <obs.h>
#include <callback/calldata.h>
#include <graphics/vec2.h>

#include <algorithm>
#include <atomic>
#include <memory>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace webobs {
namespace {

struct DataDeleter {
    void operator()(obs_data_t *value) const { obs_data_release(value); }
};
struct SourceDeleter {
    void operator()(obs_source_t *value) const { obs_source_release(value); }
};
struct SceneDeleter {
    void operator()(obs_scene_t *value) const
    {
        obs_canvas_scene_remove(value);
        obs_scene_release(value);
    }
};

using DataPtr = std::unique_ptr<obs_data_t, DataDeleter>;
using SourcePtr = std::unique_ptr<obs_source_t, SourceDeleter>;
using ScenePtr = std::unique_ptr<obs_scene_t, SceneDeleter>;

struct SourceStatus {
    std::atomic_bool started = false;
};

void on_source_started(void *parameter, calldata_t *)
{
    static_cast<SourceStatus *>(parameter)->started.store(true);
}

struct SourceEntry {
    SceneSource configuration;
    std::shared_ptr<SourceStatus> status;
    SourcePtr source;
};

struct RuntimeState {
    SceneDocument document;
    std::unordered_map<std::string, SourceEntry> sources;
    ScenePtr scene;

    ~RuntimeState()
    {
        scene.reset();
        sources.clear();
    }
};

bool connection_matches(const SceneSource &left, const SceneSource &right)
{
    return left.rtsp_url == right.rtsp_url && left.transport == right.transport;
}

SourceEntry create_source_entry(const SceneSource &configuration, int connect_timeout_seconds,
                                const RuntimeState *current)
{
    if (current) {
        const auto existing = current->sources.find(configuration.id);
        if (existing != current->sources.end() &&
            connection_matches(existing->second.configuration, configuration)) {
            SourceEntry reused;
            reused.configuration = configuration;
            reused.status = existing->second.status;
            reused.source.reset(obs_source_get_ref(existing->second.source.get()));
            return reused;
        }
    }

    DataPtr settings(obs_data_create());
    if (!settings)
        return {};
    obs_data_set_bool(settings.get(), "is_local_file", false);
    obs_data_set_string(settings.get(), "input", configuration.rtsp_url.c_str());
    obs_data_set_string(settings.get(), "input_format", "rtsp");
    obs_data_set_bool(settings.get(), "restart_on_activate", true);
    obs_data_set_bool(settings.get(), "close_when_inactive", false);
    obs_data_set_bool(settings.get(), "hw_decode", false);
    obs_data_set_int(settings.get(), "buffering_mb", 2);
    const long long timeout_microseconds = static_cast<long long>(connect_timeout_seconds) * 1000000LL;
    const std::string options =
        "rtsp_transport=" + configuration.transport + " timeout=" + std::to_string(timeout_microseconds);
    obs_data_set_string(settings.get(), "ffmpeg_options", options.c_str());

    SourceEntry entry;
    entry.configuration = configuration;
    entry.status = std::make_shared<SourceStatus>();
    const std::string internal_name = "WebOBS RTSP " + configuration.id;
    entry.source.reset(obs_source_create_private("ffmpeg_source", internal_name.c_str(), settings.get()));
    if (!entry.source) {
        entry.status.reset();
        return entry;
    }
    obs_source_set_muted(entry.source.get(), true);
    signal_handler_connect(obs_source_get_signal_handler(entry.source.get()), "media_started", on_source_started,
                           entry.status.get());
    return entry;
}

obs_bounds_type bounds_type(std::string_view scale_mode)
{
    if (scale_mode == "cover")
        return OBS_BOUNDS_SCALE_OUTER;
    if (scale_mode == "stretch")
        return OBS_BOUNDS_STRETCH;
    return OBS_BOUNDS_SCALE_INNER;
}

void configure_scene_item(obs_sceneitem_t *scene_item, const SceneItem &configuration)
{
    vec2 position{};
    vec2_set(&position, static_cast<float>(configuration.x), static_cast<float>(configuration.y));
    vec2 bounds{};
    vec2_set(&bounds, static_cast<float>(configuration.width), static_cast<float>(configuration.height));
    obs_sceneitem_set_alignment(scene_item, OBS_ALIGN_LEFT | OBS_ALIGN_TOP);
    obs_sceneitem_set_bounds_type(scene_item, bounds_type(configuration.scale_mode));
    obs_sceneitem_set_bounds_alignment(scene_item, OBS_ALIGN_CENTER);
    obs_sceneitem_set_pos(scene_item, &position);
    obs_sceneitem_set_bounds(scene_item, &bounds);
    const obs_sceneitem_crop crop = {
        .left = configuration.crop.left,
        .top = configuration.crop.top,
        .right = configuration.crop.right,
        .bottom = configuration.crop.bottom,
    };
    obs_sceneitem_set_crop(scene_item, &crop);
    obs_sceneitem_set_visible(scene_item, configuration.visible);
    obs_sceneitem_set_order_position(scene_item, configuration.z_index);
}

std::unordered_set<std::string> visible_source_ids(const RuntimeState *state)
{
    std::unordered_set<std::string> result;
    if (!state)
        return result;
    for (const SceneItem &item : state->document.items) {
        if (item.visible)
            result.insert(item.source_id);
    }
    return result;
}

bool source_ready(const SourceEntry &entry)
{
    if (!entry.source)
        return false;
    const obs_media_state state = obs_source_media_get_state(entry.source.get());
    return (entry.status->started.load() || state == OBS_MEDIA_STATE_PLAYING) &&
           obs_source_get_width(entry.source.get()) > 0 && obs_source_get_height(entry.source.get()) > 0;
}

} // namespace

struct ObsSceneRuntime::Impl {
    explicit Impl(int timeout) : connect_timeout_seconds(timeout) {}

    int connect_timeout_seconds;
    bool active = false;
    std::unique_ptr<RuntimeState> current;
    std::unique_ptr<RuntimeState> prepared;
};

ObsSceneRuntime::ObsSceneRuntime(int connect_timeout_seconds)
    : impl_(std::make_unique<Impl>(connect_timeout_seconds))
{
}

ObsSceneRuntime::~ObsSceneRuntime()
{
    deactivate();
}

std::optional<std::string> ObsSceneRuntime::prepare(const SceneDocument &document)
{
    impl_->prepared.reset();
    if (const auto validation_error = validate_scene_document(document))
        return validation_error;
    if (impl_->current && (impl_->current->document.canvas.width != document.canvas.width ||
                           impl_->current->document.canvas.height != document.canvas.height))
        return "canvas dimensions cannot change while the OBS video runtime is active";

    auto candidate = std::make_unique<RuntimeState>();
    candidate->document = document;
    static std::atomic_uint64_t scene_sequence = 0;
    const std::string scene_name = "WebOBS Program " + std::to_string(scene_sequence.fetch_add(1));
    obs_canvas_t *main_canvas = obs_get_main_canvas();
    if (!main_canvas)
        return "could not acquire the OBS main canvas";
    candidate->scene.reset(obs_canvas_scene_create(main_canvas, scene_name.c_str()));
    obs_canvas_release(main_canvas);
    if (!candidate->scene)
        return "could not create the OBS program scene";

    candidate->sources.reserve(document.sources.size());
    for (const SceneSource &source : document.sources) {
        SourceEntry entry =
            create_source_entry(source, impl_->connect_timeout_seconds, impl_->current.get());
        if (!entry.source)
            return "could not create OBS RTSP source " + source.id;
        candidate->sources.emplace(source.id, std::move(entry));
    }

    std::vector<const SceneItem *> ordered_items;
    ordered_items.reserve(document.items.size());
    for (const SceneItem &item : document.items)
        ordered_items.push_back(&item);
    std::sort(ordered_items.begin(), ordered_items.end(), [](const SceneItem *left, const SceneItem *right) {
        return left->z_index < right->z_index;
    });

    for (const SceneItem *item : ordered_items) {
        const auto source = candidate->sources.find(item->source_id);
        if (source == candidate->sources.end())
            return "scene item references a missing runtime source";
        obs_sceneitem_t *scene_item = obs_scene_add(candidate->scene.get(), source->second.source.get());
        if (!scene_item)
            return "could not add scene item " + item->id + " to the OBS program scene";
        configure_scene_item(scene_item, *item);
    }

    impl_->prepared = std::move(candidate);
    return std::nullopt;
}

bool ObsSceneRuntime::has_prepared() const
{
    return impl_->prepared != nullptr;
}

void ObsSceneRuntime::discard_prepared()
{
    impl_->prepared.reset();
}

void ObsSceneRuntime::commit_prepared()
{
    if (!impl_->prepared)
        return;
    for (const auto &[id, entry] : impl_->prepared->sources) {
        (void)id;
        obs_source_set_volume(entry.source.get(), static_cast<float>(entry.configuration.volume));
        obs_source_set_muted(entry.source.get(), entry.configuration.muted);
    }
    if (impl_->active)
        obs_set_output_source(0, obs_scene_get_source(impl_->prepared->scene.get()));
    impl_->current = std::move(impl_->prepared);
}

void ObsSceneRuntime::activate()
{
    if (impl_->active)
        return;
    impl_->active = true;
    if (impl_->current)
        obs_set_output_source(0, obs_scene_get_source(impl_->current->scene.get()));
}

void ObsSceneRuntime::deactivate()
{
    if (!impl_ || !impl_->active)
        return;
    obs_set_output_source(0, nullptr);
    impl_->active = false;
}

std::size_t ObsSceneRuntime::visible_source_count() const
{
    return visible_source_ids(impl_->current.get()).size();
}

std::size_t ObsSceneRuntime::ready_visible_source_count() const
{
    const auto visible = visible_source_ids(impl_->current.get());
    return static_cast<std::size_t>(std::count_if(visible.begin(), visible.end(), [this](const std::string &id) {
        const auto source = impl_->current->sources.find(id);
        return source != impl_->current->sources.end() && source_ready(source->second);
    }));
}

std::vector<std::string> ObsSceneRuntime::pending_visible_source_ids() const
{
    std::vector<std::string> result;
    const auto visible = visible_source_ids(impl_->current.get());
    for (const std::string &id : visible) {
        const auto source = impl_->current->sources.find(id);
        if (source == impl_->current->sources.end() || !source_ready(source->second))
            result.push_back(id);
    }
    std::sort(result.begin(), result.end());
    return result;
}

} // namespace webobs
