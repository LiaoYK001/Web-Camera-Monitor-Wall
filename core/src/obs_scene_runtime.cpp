#include "webobs/obs_scene_runtime.hpp"

#include <obs.h>
#include <callback/calldata.h>
#include <graphics/vec2.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <memory>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include <arpa/inet.h>
#include <netdb.h>
#include <sys/socket.h>

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
    std::chrono::steady_clock::time_point activated_at{};
};

void on_source_started(void *parameter, calldata_t *)
{
    static_cast<SourceStatus *>(parameter)->started.store(true);
}

struct SourceEntry {
    SceneSource configuration;
    std::shared_ptr<SourceStatus> status;
    SourcePtr source;
    bool prewarmed = false;
    bool frame_primed = false;
};

struct RuntimeState {
    SceneDocument document;
    std::unordered_map<std::string, SourceEntry> sources;
    ScenePtr scene;

    ~RuntimeState()
    {
        for (auto &[id, entry] : sources) {
            (void)id;
            if (entry.prewarmed) {
                obs_source_dec_active(entry.source.get());
                entry.prewarmed = false;
            }
        }
        scene.reset();
        sources.clear();
    }
};

bool connection_matches(const SceneSource &left, const SceneSource &right)
{
    if (left.kind != right.kind)
        return false;
    if (left.kind == "rtsp")
        return left.rtsp_url == right.rtsp_url && left.transport == right.transport;
    return left.browser_url == right.browser_url && left.browser_width == right.browser_width &&
           left.browser_height == right.browser_height && left.browser_fps == right.browser_fps &&
           left.browser_css == right.browser_css &&
           left.shutdown_when_hidden == right.shutdown_when_hidden &&
           left.restart_when_active == right.restart_when_active;
}

bool private_network_address(const sockaddr *address)
{
    if (address->sa_family == AF_INET) {
        const auto *ipv4 = reinterpret_cast<const sockaddr_in *>(address);
        const std::uint32_t value = ntohl(ipv4->sin_addr.s_addr);
        const std::uint8_t first = static_cast<std::uint8_t>(value >> 24);
        const std::uint8_t second = static_cast<std::uint8_t>(value >> 16);
        return first == 0 || first == 10 || first == 127 || first >= 224 ||
               (first == 100 && second >= 64 && second <= 127) ||
               (first == 169 && second == 254) || (first == 172 && second >= 16 && second <= 31) ||
               (first == 192 && second == 168) || (first == 198 && (second == 18 || second == 19));
    }
    if (address->sa_family == AF_INET6) {
        const auto *ipv6 = reinterpret_cast<const sockaddr_in6 *>(address);
        const unsigned char *bytes = ipv6->sin6_addr.s6_addr;
        const bool unspecified = std::all_of(bytes, bytes + 16, [](unsigned char byte) { return byte == 0; });
        const bool loopback = std::all_of(bytes, bytes + 15, [](unsigned char byte) { return byte == 0; }) &&
                              bytes[15] == 1;
        const bool unique_local = (bytes[0] & 0xfe) == 0xfc;
        const bool link_local = bytes[0] == 0xfe && (bytes[1] & 0xc0) == 0x80;
        const bool multicast = bytes[0] == 0xff;
        const bool ipv4_mapped = std::all_of(bytes, bytes + 10, [](unsigned char byte) { return byte == 0; }) &&
                                 bytes[10] == 0xff && bytes[11] == 0xff;
        if (ipv4_mapped) {
            sockaddr_in mapped{};
            mapped.sin_family = AF_INET;
            std::memcpy(&mapped.sin_addr.s_addr, bytes + 12, 4);
            return private_network_address(reinterpret_cast<const sockaddr *>(&mapped));
        }
        return unspecified || loopback || unique_local || link_local || multicast;
    }
    return true;
}

std::optional<std::string> validate_browser_destination(const SceneSource &source,
                                                        const BrowserSecurityPolicy &policy)
{
    if (source.kind != "browser")
        return std::nullopt;
    if (const auto policy_error = validate_browser_url_policy(source.browser_url, policy))
        return policy_error;
    if (policy.allow_private_networks)
        return std::nullopt;

    const BrowserUrlResult parsed = parse_browser_url(source.browser_url);
    if (!parsed.ok())
        return parsed.error;
    addrinfo hints{};
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_ADDRCONFIG;
    addrinfo *addresses = nullptr;
    const std::string port = std::to_string(parsed.parts->port);
    if (getaddrinfo(parsed.parts->host.c_str(), port.c_str(), &hints, &addresses) != 0)
        return "browser source hostname could not be resolved";
    const std::unique_ptr<addrinfo, decltype(&freeaddrinfo)> guard(addresses, freeaddrinfo);
    for (const addrinfo *address = addresses; address; address = address->ai_next) {
        if (private_network_address(address->ai_addr))
            return "browser source hostname resolves to a local or private-network destination";
    }
    return std::nullopt;
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
    if (configuration.kind == "rtsp") {
        obs_data_set_bool(settings.get(), "is_local_file", false);
        obs_data_set_string(settings.get(), "input", configuration.rtsp_url.c_str());
        obs_data_set_string(settings.get(), "input_format", "rtsp");
        obs_data_set_bool(settings.get(), "restart_on_activate", true);
        obs_data_set_bool(settings.get(), "close_when_inactive", false);
        obs_data_set_bool(settings.get(), "hw_decode", false);
        obs_data_set_int(settings.get(), "buffering_mb", 2);
        const long long timeout_microseconds =
            static_cast<long long>(connect_timeout_seconds) * 1000000LL;
        const std::string options =
            "rtsp_transport=" + configuration.transport + " timeout=" + std::to_string(timeout_microseconds);
        obs_data_set_string(settings.get(), "ffmpeg_options", options.c_str());
    } else {
        obs_data_set_string(settings.get(), "url", configuration.browser_url.c_str());
        obs_data_set_int(settings.get(), "width", configuration.browser_width);
        obs_data_set_int(settings.get(), "height", configuration.browser_height);
        obs_data_set_int(settings.get(), "fps", configuration.browser_fps);
        obs_data_set_bool(settings.get(), "fps_custom", true);
        obs_data_set_string(settings.get(), "css", configuration.browser_css.c_str());
        obs_data_set_bool(settings.get(), "shutdown", configuration.shutdown_when_hidden);
        obs_data_set_bool(settings.get(), "restart_when_active", configuration.restart_when_active);
        obs_data_set_bool(settings.get(), "reroute_audio", false);
    }

    SourceEntry entry;
    entry.configuration = configuration;
    entry.status = std::make_shared<SourceStatus>();
    const std::string internal_name = "WebOBS " + configuration.kind + " " + configuration.id;
    const char *source_type = configuration.kind == "rtsp" ? "ffmpeg_source" : "browser_source";
    entry.source.reset(obs_source_create_private(source_type, internal_name.c_str(), settings.get()));
    if (!entry.source) {
        entry.status.reset();
        return entry;
    }
    obs_source_set_muted(entry.source.get(), true);
    if (configuration.kind == "rtsp")
        signal_handler_connect(obs_source_get_signal_handler(entry.source.get()), "media_started",
                               on_source_started, entry.status.get());
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

obs_monitoring_type monitoring_type(std::string_view value)
{
    if (value == "monitor-only")
        return OBS_MONITORING_TYPE_MONITOR_ONLY;
    if (value == "monitor-and-output")
        return OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT;
    return OBS_MONITORING_TYPE_NONE;
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

bool retain_scene_item(obs_scene_t *, obs_sceneitem_t *item, void *parameter)
{
    obs_sceneitem_addref(item);
    static_cast<std::vector<obs_sceneitem_t *> *>(parameter)->push_back(item);
    return true;
}

struct AtomicSceneReplacement {
    RuntimeState *candidate;
    bool succeeded = false;
};

void replace_scene_contents(void *parameter, obs_scene_t *scene)
{
    auto &replacement = *static_cast<AtomicSceneReplacement *>(parameter);
    std::vector<obs_sceneitem_t *> previous_items;
    obs_scene_enum_items(scene, retain_scene_item, &previous_items);

    std::vector<const SceneItem *> ordered_items;
    ordered_items.reserve(replacement.candidate->document.items.size());
    for (const SceneItem &item : replacement.candidate->document.items)
        ordered_items.push_back(&item);
    std::sort(ordered_items.begin(), ordered_items.end(), [](const SceneItem *left, const SceneItem *right) {
        return left->z_index < right->z_index;
    });

    std::vector<std::pair<obs_sceneitem_t *, const SceneItem *>> added_items;
    added_items.reserve(ordered_items.size());
    for (const SceneItem *item : ordered_items) {
        const auto source = replacement.candidate->sources.find(item->source_id);
        if (source == replacement.candidate->sources.end())
            break;
        obs_sceneitem_t *scene_item = obs_scene_add(scene, source->second.source.get());
        if (!scene_item)
            break;
        added_items.emplace_back(scene_item, item);
    }

    if (added_items.size() != ordered_items.size()) {
        for (const auto &[scene_item, configuration] : added_items) {
            (void)configuration;
            obs_sceneitem_remove(scene_item);
        }
        for (obs_sceneitem_t *item : previous_items)
            obs_sceneitem_release(item);
        return;
    }

    for (obs_sceneitem_t *item : previous_items) {
        obs_sceneitem_remove(item);
        obs_sceneitem_release(item);
    }
    for (const auto &[scene_item, configuration] : added_items)
        configure_scene_item(scene_item, *configuration);
    replacement.succeeded = true;
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
    if (entry.configuration.kind == "browser") {
        return entry.status->activated_at != std::chrono::steady_clock::time_point{} &&
               std::chrono::steady_clock::now() - entry.status->activated_at >=
                   std::chrono::milliseconds(750) &&
               obs_source_get_width(entry.source.get()) > 0 && obs_source_get_height(entry.source.get()) > 0;
    }
    const obs_media_state state = obs_source_media_get_state(entry.source.get());
    return (entry.status->started.load() || state == OBS_MEDIA_STATE_PLAYING) &&
           obs_source_get_width(entry.source.get()) > 0 && obs_source_get_height(entry.source.get()) > 0;
}

bool prime_source_frame(SourceEntry &entry)
{
    if (entry.configuration.kind == "browser")
        return source_ready(entry);
    if (entry.frame_primed)
        return source_ready(entry);

    obs_source_frame *frame = obs_source_get_frame(entry.source.get());
    if (!frame)
        return false;
    obs_source_set_video_frame(entry.source.get(), frame);
    obs_source_release_frame(entry.source.get(), frame);
    entry.frame_primed = true;
    return source_ready(entry);
}

void release_prewarmed_sources(RuntimeState *state)
{
    if (!state)
        return;
    for (auto &[id, entry] : state->sources) {
        (void)id;
        if (entry.prewarmed) {
            obs_source_dec_active(entry.source.get());
            entry.prewarmed = false;
        }
    }
}

} // namespace

struct ObsSceneRuntime::Impl {
    Impl(int timeout, BrowserSecurityPolicy policy)
        : connect_timeout_seconds(timeout), browser_security(std::move(policy))
    {
    }

    int connect_timeout_seconds;
    BrowserSecurityPolicy browser_security;
    bool active = false;
    std::unique_ptr<RuntimeState> current;
    std::unique_ptr<RuntimeState> prepared;
};

ObsSceneRuntime::ObsSceneRuntime(int connect_timeout_seconds, BrowserSecurityPolicy browser_security)
    : impl_(std::make_unique<Impl>(connect_timeout_seconds, std::move(browser_security)))
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
        if (const auto browser_error = validate_browser_destination(source, impl_->browser_security))
            return "browser source " + source.id + " rejected: " + *browser_error;
        SourceEntry entry =
            create_source_entry(source, impl_->connect_timeout_seconds, impl_->current.get());
        if (!entry.source)
            return "could not create OBS " + source.kind + " source " + source.id;
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

    const auto visible = visible_source_ids(candidate.get());
    for (const std::string &id : visible) {
        auto source = candidate->sources.find(id);
        if (source != candidate->sources.end()) {
            const bool already_active = obs_source_active(source->second.source.get());
            source->second.frame_primed = already_active;
            if (!already_active) {
                source->second.status->started.store(false);
                source->second.status->activated_at = std::chrono::steady_clock::now();
            } else if (source->second.status->activated_at == std::chrono::steady_clock::time_point{}) {
                source->second.status->activated_at = std::chrono::steady_clock::now();
            }
            obs_source_inc_active(source->second.source.get());
            source->second.prewarmed = true;
        }
    }

    impl_->prepared = std::move(candidate);
    return std::nullopt;
}

bool ObsSceneRuntime::has_prepared() const
{
    return impl_->prepared != nullptr;
}

std::optional<std::string> ObsSceneRuntime::wait_prepared_visible_sources()
{
    if (!impl_->prepared)
        return "no OBS scene replacement is prepared";

    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::seconds(impl_->connect_timeout_seconds);
    std::vector<std::string> pending;
    while (true) {
        pending.clear();
        const auto visible = visible_source_ids(impl_->prepared.get());
        for (const std::string &id : visible) {
            auto source = impl_->prepared->sources.find(id);
            if (source == impl_->prepared->sources.end() || !prime_source_frame(source->second))
                pending.push_back(id);
        }
        if (pending.empty())
            return std::nullopt;
        if (std::chrono::steady_clock::now() >= deadline)
            break;
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    std::sort(pending.begin(), pending.end());
    std::string message = "scene sources did not become ready before timeout:";
    for (const std::string &id : pending)
        message += " " + id;
    return message;
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
        obs_source_set_sync_offset(entry.source.get(),
                                   static_cast<std::int64_t>(entry.configuration.sync_offset_ms) * 1000000LL);
        obs_source_set_audio_mixers(entry.source.get(),
                                    1U << static_cast<unsigned int>(entry.configuration.audio_track - 1));
        obs_source_set_monitoring_type(entry.source.get(),
                                       monitoring_type(entry.configuration.monitoring));
    }
    if (impl_->active && impl_->current) {
        AtomicSceneReplacement replacement{impl_->prepared.get()};
        obs_scene_atomic_update(impl_->current->scene.get(), replace_scene_contents, &replacement);
        if (replacement.succeeded) {
            impl_->prepared->scene.reset();
            impl_->prepared->scene = std::move(impl_->current->scene);
        } else {
            blog(LOG_ERROR, "Could not atomically replace the active OBS scene; using prepared scene output");
            obs_set_output_source(0, obs_scene_get_source(impl_->prepared->scene.get()));
        }
    } else if (impl_->active) {
        obs_set_output_source(0, obs_scene_get_source(impl_->prepared->scene.get()));
    }
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
    release_prewarmed_sources(impl_->current.get());
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
