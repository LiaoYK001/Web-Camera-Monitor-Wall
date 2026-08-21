#include "webobs/obs_scene_runtime.hpp"

#include "webobs/audit_event.hpp"

#include <obs.h>
#include <curl/curl.h>
#include <jansson.h>
#include <callback/calldata.h>
#include <graphics/vec2.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <memory>
#include <mutex>
#include <new>
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
    std::atomic_uint64_t frame_count = 0;
    std::chrono::steady_clock::time_point activated_at{};
    std::chrono::steady_clock::time_point last_frame_at{};
    std::chrono::steady_clock::time_point next_recovery_at{};
    std::uint64_t last_observed_frame_count = 0;
    std::uint64_t restart_count = 0;
    unsigned int consecutive_restarts = 0;
    bool recovering = false;
    bool stale_reported = false;
};

const char *health_filter_name(void *)
{
    return "WebOBS frame health filter";
}

void *health_filter_create(obs_data_t *settings, obs_source_t *)
{
    const auto address = static_cast<std::uintptr_t>(obs_data_get_int(settings, "status_address"));
    const auto *status = reinterpret_cast<const std::shared_ptr<SourceStatus> *>(address);
    if (!status || !*status)
        return nullptr;
    return new (std::nothrow) std::shared_ptr<SourceStatus>(*status);
}

void health_filter_destroy(void *data)
{
    delete static_cast<std::shared_ptr<SourceStatus> *>(data);
}

obs_source_frame *health_filter_video(void *data, obs_source_frame *frame)
{
    const auto *status = static_cast<const std::shared_ptr<SourceStatus> *>(data);
    if (status && *status && frame)
        (*status)->frame_count.fetch_add(1, std::memory_order_relaxed);
    return frame;
}

void register_source_health_filter()
{
    static std::once_flag registered;
    std::call_once(registered, [] {
        obs_source_info info{};
        info.id = "webobs_frame_health_filter";
        info.type = OBS_SOURCE_TYPE_FILTER;
        info.output_flags = OBS_SOURCE_VIDEO | OBS_SOURCE_ASYNC;
        info.get_name = health_filter_name;
        info.create = health_filter_create;
        info.destroy = health_filter_destroy;
        info.filter_video = health_filter_video;
        obs_register_source(&info);
    });
}

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
    if (left.kind == "camera")
        return left.camera_id == right.camera_id && left.profile_id == right.profile_id &&
               left.hardware_decode == right.hardware_decode;
    if (left.kind == "browser")
        return left.browser_url == right.browser_url && left.browser_width == right.browser_width &&
               left.browser_height == right.browser_height && left.browser_fps == right.browser_fps &&
               left.browser_css == right.browser_css &&
               left.shutdown_when_hidden == right.shutdown_when_hidden &&
               left.restart_when_active == right.restart_when_active && left.filters == right.filters;
    return left.file_path == right.file_path && left.text == right.text && left.color == right.color &&
           left.loop == right.loop && left.filters == right.filters;
}

struct ResolvedCameraSource {
    std::string endpoint;
    std::string adapter;
    std::string hardware_decode;
};

std::optional<ResolvedCameraSource> resolve_camera_source(const SceneSource &source)
{
    std::string body;
    CURL *handle = curl_easy_init();
    if (!handle)
        return std::nullopt;
    const std::string url = "http://127.0.0.1:8092/resolve/" + source.camera_id + "/" + source.profile_id;
    const auto write = [](char *data, std::size_t size, std::size_t count, void *context) -> std::size_t {
        const std::size_t bytes = size * count;
        auto &output = *static_cast<std::string *>(context);
        if (bytes > 8192 || output.size() > 8192 - bytes)
            return 0;
        output.append(data, bytes);
        return bytes;
    };
    curl_easy_setopt(handle, CURLOPT_URL, url.c_str());
    curl_easy_setopt(handle, CURLOPT_PROTOCOLS_STR, "http");
    curl_easy_setopt(handle, CURLOPT_CONNECTTIMEOUT_MS, 1000L);
    curl_easy_setopt(handle, CURLOPT_TIMEOUT_MS, 3000L);
    curl_easy_setopt(handle, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(handle, CURLOPT_WRITEFUNCTION, +write);
    curl_easy_setopt(handle, CURLOPT_WRITEDATA, &body);
    const CURLcode code = curl_easy_perform(handle);
    long status = 0;
    if (code == CURLE_OK)
        curl_easy_getinfo(handle, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(handle);
    if (code != CURLE_OK || status != 200)
        return std::nullopt;
    json_error_t error{};
    json_t *root = json_loadb(body.data(), body.size(), JSON_REJECT_DUPLICATES, &error);
    if (!root || !json_is_object(root)) {
        json_decref(root);
        return std::nullopt;
    }
    json_t *endpoint = json_object_get(root, "endpoint");
    json_t *adapter = json_object_get(root, "adapter");
    json_t *hardware = json_object_get(root, "hardwareDecode");
    std::optional<ResolvedCameraSource> result;
    if (json_is_string(endpoint) && json_is_string(adapter) && json_is_string(hardware))
        result = ResolvedCameraSource{json_string_value(endpoint), json_string_value(adapter),
                                      json_string_value(hardware)};
    json_decref(root);
    return result;
}

std::uint32_t obs_color(std::string_view color)
{
    const auto component = [color](std::size_t offset) {
        return static_cast<std::uint32_t>(std::stoul(std::string(color.substr(offset, 2)), nullptr, 16));
    };
    const std::uint32_t red = component(1);
    const std::uint32_t green = component(3);
    const std::uint32_t blue = component(5);
    return 0xff000000U | (blue << 16U) | (green << 8U) | red;
}

bool attach_configured_filters(obs_source_t *source, const SceneSource &configuration,
                               std::string_view internal_name)
{
    for (const SceneFilter &filter : configuration.filters) {
        DataPtr settings(obs_data_create());
        if (!settings)
            return false;
        const char *filter_type = nullptr;
        if (filter.kind == "opacity") {
            filter_type = "color_filter";
            obs_data_set_int(settings.get(), "opacity", static_cast<long long>(filter.amount * 100.0));
        } else if (filter.kind == "color-correction") {
            filter_type = "color_filter";
            obs_data_set_double(settings.get(), "brightness", filter.amount);
        } else if (filter.kind == "delay") {
            filter_type = "async_delay_filter";
            obs_data_set_int(settings.get(), "delay_ms", static_cast<long long>(filter.amount));
        } else if (filter.kind == "scaling") {
            filter_type = "scale_filter";
            obs_data_set_string(settings.get(), "resolution", filter.value.c_str());
            obs_data_set_string(settings.get(), "sampling", "bicubic");
        } else if (filter.kind == "lut") {
            filter_type = "clut_filter";
            obs_data_set_string(settings.get(), "image_path", filter.value.c_str());
            obs_data_set_double(settings.get(), "clut_amount", filter.amount);
        } else if (filter.kind == "mask-blend") {
            filter_type = "mask_filter";
            obs_data_set_string(settings.get(), "image_path", filter.value.c_str());
            obs_data_set_int(settings.get(), "opacity", static_cast<long long>(filter.amount * 100.0));
        } else if (filter.kind == "crop-pad") {
            filter_type = "crop_filter";
            obs_data_set_bool(settings.get(), "relative", true);
            long long crop = static_cast<long long>(filter.amount);
            obs_data_set_int(settings.get(), "left", crop);
            obs_data_set_int(settings.get(), "top", crop);
            obs_data_set_int(settings.get(), "right", crop);
            obs_data_set_int(settings.get(), "bottom", crop);
        }
        if (!filter_type)
            return false;
        const std::string name = std::string(internal_name) + " filter " + filter.id;
        SourcePtr instance(obs_source_create_private(filter_type, name.c_str(), settings.get()));
        if (!instance)
            return false;
        obs_source_filter_add(source, instance.get());
        obs_source_set_enabled(instance.get(), filter.enabled);
    }
    return true;
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
                                const RuntimeState *current, bool hardware_decode_enabled)
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
    if (configuration.kind == "rtsp" || configuration.kind == "camera") {
        std::string input = configuration.rtsp_url;
        std::string adapter = "rtsp";
        std::string decode_override = "auto";
        if (configuration.kind == "camera") {
            const auto resolved = resolve_camera_source(configuration);
            if (!resolved)
                return {};
            input = resolved->endpoint;
            adapter = resolved->adapter;
            decode_override = configuration.hardware_decode == "auto"
                                  ? resolved->hardware_decode : configuration.hardware_decode;
        }
        // A per-camera "on" preference must not bypass the runtime capability
        // probe. The resolved global flag is false when VA-API initialization
        // failed, so every requested hardware path safely falls back to FFmpeg's
        // software decoder instead of failing the source outright.
        const bool source_hardware_decode = decode_override != "off" && hardware_decode_enabled;
        obs_data_set_bool(settings.get(), "is_local_file", false);
        obs_data_set_string(settings.get(), "input", input.c_str());
        if (adapter == "rtsp")
            obs_data_set_string(settings.get(), "input_format", "rtsp");
        obs_data_set_bool(settings.get(), "restart_on_activate", true);
        obs_data_set_bool(settings.get(), "close_when_inactive", false);
        obs_data_set_bool(settings.get(), "hw_decode", source_hardware_decode);
        obs_data_set_int(settings.get(), "buffering_mb", 2);
        const long long timeout_microseconds =
            static_cast<long long>(connect_timeout_seconds) * 1000000LL;
        const std::string transport = configuration.kind == "rtsp" ? configuration.transport : "tcp";
        const std::string options = adapter == "rtsp"
            ? "rtsp_transport=" + transport + " timeout=" + std::to_string(timeout_microseconds)
            : "rw_timeout=" + std::to_string(timeout_microseconds);
        obs_data_set_string(settings.get(), "ffmpeg_options", options.c_str());
    } else if (configuration.kind == "browser") {
        obs_data_set_string(settings.get(), "url", configuration.browser_url.c_str());
        obs_data_set_int(settings.get(), "width", configuration.browser_width);
        obs_data_set_int(settings.get(), "height", configuration.browser_height);
        obs_data_set_int(settings.get(), "fps", configuration.browser_fps);
        obs_data_set_bool(settings.get(), "fps_custom", true);
        obs_data_set_string(settings.get(), "css", configuration.browser_css.c_str());
        obs_data_set_bool(settings.get(), "shutdown", configuration.shutdown_when_hidden);
        obs_data_set_bool(settings.get(), "restart_when_active", configuration.restart_when_active);
        obs_data_set_bool(settings.get(), "reroute_audio", false);
    } else if (configuration.kind == "image") {
        obs_data_set_string(settings.get(), "file", configuration.file_path.c_str());
        obs_data_set_bool(settings.get(), "unload", false);
    } else if (configuration.kind == "media") {
        obs_data_set_bool(settings.get(), "is_local_file", true);
        obs_data_set_string(settings.get(), "local_file", configuration.file_path.c_str());
        obs_data_set_bool(settings.get(), "looping", configuration.loop);
        obs_data_set_bool(settings.get(), "restart_on_activate", true);
        obs_data_set_bool(settings.get(), "close_when_inactive", false);
        obs_data_set_bool(settings.get(), "hw_decode", hardware_decode_enabled);
    } else if (configuration.kind == "color") {
        obs_data_set_int(settings.get(), "color", obs_color(configuration.color));
        obs_data_set_int(settings.get(), "width", 1920);
        obs_data_set_int(settings.get(), "height", 1080);
    } else if (configuration.kind == "text") {
        obs_data_set_string(settings.get(), "text", configuration.text.c_str());
        obs_data_set_int(settings.get(), "color", obs_color(configuration.color));
        DataPtr font(obs_data_create());
        if (!font)
            return {};
        obs_data_set_string(font.get(), "face", "Liberation Sans");
        obs_data_set_string(font.get(), "style", "Regular");
        obs_data_set_int(font.get(), "size", 48);
        obs_data_set_int(font.get(), "flags", 0);
        obs_data_set_obj(settings.get(), "font", font.get());
    } else {
        return {};
    }

    SourceEntry entry;
    entry.configuration = configuration;
    entry.status = std::make_shared<SourceStatus>();
    const std::string internal_name = "WebOBS " + configuration.kind + " " + configuration.id;
    const char *source_type = configuration.kind == "rtsp" || configuration.kind == "camera" || configuration.kind == "media"
                                  ? "ffmpeg_source"
                              : configuration.kind == "browser" ? "browser_source"
                              : configuration.kind == "image"   ? "image_source"
                              : configuration.kind == "color"   ? "color_source"
                                                                : "text_ft2_source";
    entry.source.reset(obs_source_create_private(source_type, internal_name.c_str(), settings.get()));
    if (!entry.source) {
        entry.status.reset();
        return entry;
    }
    obs_source_set_muted(entry.source.get(), true);
    if (!attach_configured_filters(entry.source.get(), configuration, internal_name)) {
        entry.source.reset();
        entry.status.reset();
        return entry;
    }
    if (configuration.kind == "rtsp" || configuration.kind == "camera")
        signal_handler_connect(obs_source_get_signal_handler(entry.source.get()), "media_started",
                               on_source_started, entry.status.get());
    if (configuration.kind == "rtsp" || configuration.kind == "camera") {
        DataPtr filter_settings(obs_data_create());
        if (!filter_settings) {
            entry.source.reset();
            entry.status.reset();
            return entry;
        }
        obs_data_set_int(filter_settings.get(), "status_address",
                         static_cast<long long>(reinterpret_cast<std::uintptr_t>(&entry.status)));
        const std::string filter_name = internal_name + " frame health";
        SourcePtr filter(obs_source_create_private("webobs_frame_health_filter", filter_name.c_str(),
                                                   filter_settings.get()));
        if (!filter) {
            entry.source.reset();
            entry.status.reset();
            return entry;
        }
        const std::size_t previous_filter_count = obs_source_filter_count(entry.source.get());
        obs_source_filter_add(entry.source.get(), filter.get());
        if (obs_source_filter_count(entry.source.get()) != previous_filter_count + 1) {
            entry.source.reset();
            entry.status.reset();
            return entry;
        }
    }
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
    obs_sceneitem_set_rot(scene_item, static_cast<float>(configuration.rotation_degrees));
    obs_blending_type blending = OBS_BLEND_NORMAL;
    if (configuration.blend_mode == "add")
        blending = OBS_BLEND_ADDITIVE;
    else if (configuration.blend_mode == "multiply")
        blending = OBS_BLEND_MULTIPLY;
    else if (configuration.blend_mode == "screen")
        blending = OBS_BLEND_SCREEN;
    obs_sceneitem_set_blending_mode(scene_item, blending);
    obs_sceneitem_set_visible(scene_item, configuration.visible);
    obs_sceneitem_set_order_position(scene_item, configuration.z_index);
}

obs_sceneitem_t *add_scene_item(obs_scene_t *scene, obs_source_t *source,
                                const SceneItem &configuration)
{
    obs_sceneitem_t *item = obs_scene_add(scene, source);
    if (!item)
        return nullptr;
    if (configuration.opacity >= 0.999999) {
        configure_scene_item(item, configuration);
        return item;
    }

    static std::atomic_uint64_t group_sequence = 0;
    const std::string group_name = "WebOBS item opacity " + configuration.id + " " +
                                   std::to_string(group_sequence.fetch_add(1));
    obs_sceneitem_t *group = obs_scene_insert_group2(scene, group_name.c_str(), &item, 1, false);
    if (!group) {
        obs_sceneitem_remove(item);
        return nullptr;
    }

    DataPtr settings(obs_data_create());
    if (!settings) {
        obs_sceneitem_remove(group);
        return nullptr;
    }
    obs_data_set_int(settings.get(), "opacity",
                     static_cast<long long>(std::lround(configuration.opacity * 100.0)));
    const std::string filter_name = group_name + " filter";
    SourcePtr filter(obs_source_create_private("color_filter", filter_name.c_str(), settings.get()));
    obs_source_t *group_source = obs_sceneitem_get_source(group);
    if (!filter || !group_source) {
        obs_sceneitem_remove(group);
        return nullptr;
    }
    const std::size_t previous_filter_count = obs_source_filter_count(group_source);
    obs_source_filter_add(group_source, filter.get());
    if (obs_source_filter_count(group_source) != previous_filter_count + 1) {
        obs_sceneitem_remove(group);
        return nullptr;
    }
    configure_scene_item(group, configuration);
    return group;
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
        obs_sceneitem_t *scene_item = add_scene_item(scene, source->second.source.get(), *item);
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
    if (entry.configuration.kind == "image" || entry.configuration.kind == "color" ||
        entry.configuration.kind == "text")
        return obs_source_get_width(entry.source.get()) > 0 && obs_source_get_height(entry.source.get()) > 0;
    if (entry.configuration.kind == "media") {
        const obs_media_state state = obs_source_media_get_state(entry.source.get());
        return (state == OBS_MEDIA_STATE_PLAYING || state == OBS_MEDIA_STATE_PAUSED) &&
               obs_source_get_width(entry.source.get()) > 0 && obs_source_get_height(entry.source.get()) > 0;
    }
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

bool observe_latest_frame(SourceEntry &entry, std::chrono::steady_clock::time_point now)
{
    if (!entry.source || (entry.configuration.kind != "rtsp" && entry.configuration.kind != "camera"))
        return false;
    const std::uint64_t frame_count = entry.status->frame_count.load(std::memory_order_relaxed);
    if (frame_count == entry.status->last_observed_frame_count)
        return false;

    const bool recovered = entry.status->recovering || entry.status->stale_reported;
    entry.status->last_observed_frame_count = frame_count;
    entry.status->last_frame_at = now;
    entry.status->consecutive_restarts = 0;
    entry.status->recovering = false;
    entry.status->next_recovery_at = {};
    entry.status->stale_reported = false;
    if (recovered) {
        const std::string restarts = std::to_string(entry.status->restart_count);
        const std::string event = format_audit_event(
            "source_health", "recovered",
            {{"source_id", entry.configuration.id}, {"restart_count", restarts}});
        blog(LOG_INFO, "%s", event.c_str());
    }
    return true;
}

std::string source_health_state(const SourceEntry &entry, bool visible,
                                std::chrono::steady_clock::time_point now,
                                std::chrono::seconds stale_threshold)
{
    if (!visible)
        return "idle";
    if (entry.configuration.kind != "rtsp" && entry.configuration.kind != "camera") {
        if (source_ready(entry))
            return "healthy";
        if (entry.status->activated_at != std::chrono::steady_clock::time_point{} &&
            now - entry.status->activated_at < stale_threshold)
            return "starting";
        return "stale";
    }
    if (entry.status->last_frame_at != std::chrono::steady_clock::time_point{} &&
        now - entry.status->last_frame_at < stale_threshold)
        return "healthy";
    if (entry.status->last_frame_at == std::chrono::steady_clock::time_point{} &&
        entry.status->activated_at != std::chrono::steady_clock::time_point{} &&
        now - entry.status->activated_at < stale_threshold)
        return "starting";
    return entry.status->recovering ? "recovering" : "stale";
}

bool prime_source_frame(SourceEntry &entry)
{
    if (entry.configuration.kind != "rtsp" && entry.configuration.kind != "camera")
        return source_ready(entry);
    if (entry.frame_primed)
        return source_ready(entry);

    obs_source_frame *frame = obs_source_get_frame(entry.source.get());
    if (!frame)
        return false;
    obs_source_set_video_frame(entry.source.get(), frame);
    entry.status->last_observed_frame_count =
        entry.status->frame_count.load(std::memory_order_relaxed);
    entry.status->last_frame_at = std::chrono::steady_clock::now();
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
    Impl(int timeout, BrowserSecurityPolicy policy, int stale_seconds, int recovery_base_seconds,
         int recovery_max_seconds, bool hardware_decode, bool runtime)
        : connect_timeout_seconds(timeout), browser_security(std::move(policy)),
          source_stale_seconds(stale_seconds), source_recovery_base_seconds(recovery_base_seconds),
          source_recovery_max_seconds(recovery_max_seconds), hardware_decode_enabled(hardware_decode),
          runtime_enabled(runtime)
    {
    }

    mutable std::mutex mutex;
    int connect_timeout_seconds;
    BrowserSecurityPolicy browser_security;
    int source_stale_seconds;
    int source_recovery_base_seconds;
    int source_recovery_max_seconds;
    bool hardware_decode_enabled;
    bool runtime_enabled;
    bool disabled_prepared = false;
    std::uint64_t total_restarts = 0;
    bool active = false;
    std::unique_ptr<RuntimeState> current;
    std::unique_ptr<RuntimeState> prepared;
    SourcePtr transition;
};

ObsSceneRuntime::ObsSceneRuntime(int connect_timeout_seconds, BrowserSecurityPolicy browser_security,
                                 int source_stale_seconds, int source_recovery_base_seconds,
                                 int source_recovery_max_seconds, bool hardware_decode_enabled,
                                 bool runtime_enabled)
    : impl_(std::make_unique<Impl>(connect_timeout_seconds, std::move(browser_security),
                                  source_stale_seconds, source_recovery_base_seconds,
                                  source_recovery_max_seconds, hardware_decode_enabled,
                                  runtime_enabled))
{
    if (runtime_enabled)
        register_source_health_filter();
}

ObsSceneRuntime::~ObsSceneRuntime()
{
    deactivate();
}

std::optional<std::string> ObsSceneRuntime::prepare(const SceneDocument &document)
{
    std::lock_guard lock(impl_->mutex);
    impl_->prepared.reset();
    impl_->disabled_prepared = false;
    if (const auto validation_error = validate_scene_document(document))
        return validation_error;
    if (!impl_->runtime_enabled) {
        for (const SceneSource &source : document.sources) {
            if (const auto browser_error = validate_browser_destination(source, impl_->browser_security))
                return "browser source " + source.id + " rejected: " + *browser_error;
        }
        impl_->disabled_prepared = true;
        return std::nullopt;
    }
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
            create_source_entry(source, impl_->connect_timeout_seconds, impl_->current.get(),
                                impl_->hardware_decode_enabled);
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
        obs_sceneitem_t *scene_item =
            add_scene_item(candidate->scene.get(), source->second.source.get(), *item);
        if (!scene_item)
            return "could not add scene item " + item->id + " to the OBS program scene";
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
    std::lock_guard lock(impl_->mutex);
    return impl_->prepared != nullptr || impl_->disabled_prepared;
}

std::optional<std::string> ObsSceneRuntime::wait_prepared_visible_sources()
{
    std::lock_guard lock(impl_->mutex);
    if (!impl_->runtime_enabled)
        return impl_->disabled_prepared ? std::nullopt :
               std::optional<std::string>("no scene replacement is prepared");
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
    std::lock_guard lock(impl_->mutex);
    impl_->prepared.reset();
    impl_->disabled_prepared = false;
}

void ObsSceneRuntime::commit_prepared()
{
    commit_prepared("cut", 0);
}

void ObsSceneRuntime::commit_prepared(std::string_view transition_kind, int duration_ms)
{
    std::lock_guard lock(impl_->mutex);
    if (!impl_->runtime_enabled) {
        impl_->disabled_prepared = false;
        return;
    }
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
    bool fade_started = false;
    if (impl_->active && impl_->current && transition_kind == "fade" && duration_ms > 0) {
        if (!impl_->transition)
            impl_->transition.reset(
                obs_source_create_private("fade_transition", "WebOBS Studio Fade", nullptr));
        if (impl_->transition) {
            obs_transition_set(impl_->transition.get(), obs_scene_get_source(impl_->current->scene.get()));
            obs_set_output_source(0, impl_->transition.get());
            fade_started = obs_transition_start(impl_->transition.get(), OBS_TRANSITION_MODE_AUTO,
                                                static_cast<std::uint32_t>(duration_ms),
                                                obs_scene_get_source(impl_->prepared->scene.get()));
            if (!fade_started) {
                blog(LOG_WARNING, "Could not start fade transition; applying an atomic cut");
                obs_set_output_source(0, obs_scene_get_source(impl_->prepared->scene.get()));
                impl_->transition.reset();
            }
        } else {
            blog(LOG_WARNING, "Could not create fade transition; applying an atomic cut");
            AtomicSceneReplacement replacement{impl_->prepared.get()};
            obs_scene_atomic_update(impl_->current->scene.get(), replace_scene_contents, &replacement);
            if (replacement.succeeded) {
                impl_->prepared->scene.reset();
                impl_->prepared->scene = std::move(impl_->current->scene);
            } else {
                obs_set_output_source(0, obs_scene_get_source(impl_->prepared->scene.get()));
            }
        }
    } else if (impl_->active && impl_->current) {
        if (impl_->transition) {
            obs_set_output_source(0, obs_scene_get_source(impl_->current->scene.get()));
            impl_->transition.reset();
        }
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
    if (fade_started) {
        std::this_thread::sleep_for(std::chrono::milliseconds(duration_ms + 34));
        obs_set_output_source(0, obs_scene_get_source(impl_->prepared->scene.get()));
        impl_->transition.reset();
    }
    impl_->current = std::move(impl_->prepared);
}

void ObsSceneRuntime::activate()
{
    std::lock_guard lock(impl_->mutex);
    if (!impl_->runtime_enabled)
        return;
    if (impl_->active)
        return;
    impl_->active = true;
    if (impl_->current)
        obs_set_output_source(0, obs_scene_get_source(impl_->current->scene.get()));
}

void ObsSceneRuntime::deactivate()
{
    if (!impl_)
        return;
    std::lock_guard lock(impl_->mutex);
    if (!impl_->runtime_enabled)
        return;
    if (!impl_->active)
        return;
    obs_set_output_source(0, nullptr);
    impl_->transition.reset();
    release_prewarmed_sources(impl_->current.get());
    impl_->active = false;
}

std::size_t ObsSceneRuntime::visible_source_count() const
{
    std::lock_guard lock(impl_->mutex);
    if (!impl_->runtime_enabled)
        return 0;
    return visible_source_ids(impl_->current.get()).size();
}

std::size_t ObsSceneRuntime::ready_visible_source_count() const
{
    std::lock_guard lock(impl_->mutex);
    if (!impl_->runtime_enabled)
        return 0;
    const auto visible = visible_source_ids(impl_->current.get());
    return static_cast<std::size_t>(std::count_if(visible.begin(), visible.end(), [this](const std::string &id) {
        const auto source = impl_->current->sources.find(id);
        return source != impl_->current->sources.end() && source_ready(source->second);
    }));
}

std::vector<std::string> ObsSceneRuntime::pending_visible_source_ids() const
{
    std::lock_guard lock(impl_->mutex);
    if (!impl_->runtime_enabled)
        return {};
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

void ObsSceneRuntime::maintain_source_health()
{
    std::lock_guard lock(impl_->mutex);
    if (!impl_->runtime_enabled)
        return;
    if (!impl_->current || !impl_->active)
        return;
    const auto now = std::chrono::steady_clock::now();
    const auto stale_threshold = std::chrono::seconds(impl_->source_stale_seconds);
    const auto visible = visible_source_ids(impl_->current.get());
    for (auto &[id, entry] : impl_->current->sources) {
        const bool is_visible = visible.contains(id);
        if (!is_visible)
            continue;
        observe_latest_frame(entry, now);
        const std::string state = source_health_state(entry, true, now, stale_threshold);
        if (state == "healthy" || state == "starting")
            continue;
        if (!entry.status->stale_reported) {
            entry.status->stale_reported = true;
            const std::string event = format_audit_event(
                "source_health", "unavailable", {{"source_id", id}, {"source_kind", entry.configuration.kind}});
            blog(LOG_WARNING, "%s", event.c_str());
        }
        if ((entry.configuration.kind != "rtsp" && entry.configuration.kind != "camera") ||
            (entry.status->next_recovery_at != std::chrono::steady_clock::time_point{} &&
             now < entry.status->next_recovery_at))
            continue;

        obs_source_media_restart(entry.source.get());
        ++entry.status->restart_count;
        ++impl_->total_restarts;
        ++entry.status->consecutive_restarts;
        entry.status->recovering = true;
        int backoff = impl_->source_recovery_base_seconds;
        for (unsigned int attempt = 1; attempt < entry.status->consecutive_restarts &&
                                       backoff < impl_->source_recovery_max_seconds;
             ++attempt) {
            backoff = std::min(backoff * 2, impl_->source_recovery_max_seconds);
        }
        entry.status->next_recovery_at = now + std::chrono::seconds(backoff);
        const std::string restart_count = std::to_string(entry.status->restart_count);
        const std::string retry_seconds = std::to_string(backoff);
        const std::string event = format_audit_event(
            "source_recovery", "restart_requested",
            {{"source_id", id}, {"restart_count", restart_count}, {"next_retry_seconds", retry_seconds}});
        blog(LOG_WARNING, "%s", event.c_str());
    }
}

SourceHealthSnapshot ObsSceneRuntime::source_health_snapshot() const
{
    std::lock_guard lock(impl_->mutex);
    SourceHealthSnapshot snapshot;
    if (!impl_->runtime_enabled)
        return snapshot;
    snapshot.total_restarts = impl_->total_restarts;
    if (!impl_->current)
        return snapshot;
    const auto now = std::chrono::steady_clock::now();
    const auto stale_threshold = std::chrono::seconds(impl_->source_stale_seconds);
    const auto visible = visible_source_ids(impl_->current.get());
    snapshot.sources.reserve(impl_->current->sources.size());
    for (const auto &[id, entry] : impl_->current->sources) {
        SourceHealthEntry health;
        health.id = id;
        health.kind = entry.configuration.kind;
        health.visible = visible.contains(id);
        health.state = source_health_state(entry, health.visible, now, stale_threshold);
        health.restart_count = entry.status->restart_count;
        if (entry.status->last_frame_at != std::chrono::steady_clock::time_point{})
            health.last_frame_age_ms =
                std::chrono::duration_cast<std::chrono::milliseconds>(now - entry.status->last_frame_at).count();
        if (health.visible) {
            ++snapshot.visible;
            if (health.state == "healthy")
                ++snapshot.healthy;
            else
                ++snapshot.unhealthy;
        }
        snapshot.sources.push_back(std::move(health));
    }
    std::sort(snapshot.sources.begin(), snapshot.sources.end(),
              [](const SourceHealthEntry &left, const SourceHealthEntry &right) {
                  return left.id < right.id;
              });
    return snapshot;
}

} // namespace webobs
