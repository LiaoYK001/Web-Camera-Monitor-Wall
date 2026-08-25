#include "webobs/scene_document.hpp"

#include "webobs/browser_security.hpp"
#include "webobs/redaction.hpp"

#include <jansson.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <initializer_list>
#include <limits>
#include <memory>
#include <string>
#include <unordered_set>
#include <utility>

namespace webobs {
namespace {

struct JsonDeleter {
    void operator()(json_t *value) const { json_decref(value); }
};

using JsonPtr = std::unique_ptr<json_t, JsonDeleter>;

SceneParseResult parse_failure(std::string message)
{
    SceneParseResult result;
    result.error = std::move(message);
    return result;
}

SceneSerializeResult serialize_failure(std::string message)
{
    SceneSerializeResult result;
    result.error = std::move(message);
    return result;
}

bool has_only_fields(const json_t *object, std::initializer_list<std::string_view> allowed)
{
    const char *key = nullptr;
    json_t *value = nullptr;
    json_object_foreach(const_cast<json_t *>(object), key, value)
    {
        (void)value;
        if (std::none_of(allowed.begin(), allowed.end(),
                         [key](std::string_view candidate) { return candidate == key; }))
            return false;
    }
    return true;
}

bool read_string(const json_t *object, const char *key, std::string &target, std::size_t maximum,
                 std::string &error, std::string_view context)
{
    json_t *value = json_object_get(object, key);
    if (!json_is_string(value)) {
        error = std::string(context) + " must contain a string field named " + key;
        return false;
    }
    const std::size_t length = json_string_length(value);
    if (length == 0 || length > maximum) {
        error = std::string(context) + " field " + key + " has an invalid length";
        return false;
    }
    target.assign(json_string_value(value), length);
    return true;
}

bool read_string_allow_empty(const json_t *object, const char *key, std::string &target,
                             std::size_t maximum, std::string &error, std::string_view context)
{
    json_t *value = json_object_get(object, key);
    if (!json_is_string(value)) {
        error = std::string(context) + " must contain a string field named " + key;
        return false;
    }
    const std::size_t length = json_string_length(value);
    if (length > maximum) {
        error = std::string(context) + " field " + key + " has an invalid length";
        return false;
    }
    target.assign(json_string_value(value), length);
    return true;
}

bool read_integer(const json_t *object, const char *key, int minimum, int maximum, int &target,
                  std::string &error, std::string_view context)
{
    json_t *value = json_object_get(object, key);
    if (!json_is_integer(value)) {
        error = std::string(context) + " must contain an integer field named " + key;
        return false;
    }
    const json_int_t parsed = json_integer_value(value);
    if (parsed < minimum || parsed > maximum) {
        error = std::string(context) + " field " + key + " is out of range";
        return false;
    }
    target = static_cast<int>(parsed);
    return true;
}

bool read_boolean(const json_t *object, const char *key, bool &target, std::string &error,
                  std::string_view context)
{
    json_t *value = json_object_get(object, key);
    if (!json_is_boolean(value)) {
        error = std::string(context) + " must contain a boolean field named " + key;
        return false;
    }
    target = json_is_true(value);
    return true;
}

bool read_number(const json_t *object, const char *key, double &target, std::string &error,
                 std::string_view context)
{
    json_t *value = json_object_get(object, key);
    if (!json_is_number(value)) {
        error = std::string(context) + " must contain a numeric field named " + key;
        return false;
    }
    target = json_number_value(value);
    if (!std::isfinite(target)) {
        error = std::string(context) + " field " + key + " must be finite";
        return false;
    }
    return true;
}

bool valid_identifier(std::string_view value)
{
    if (value.empty() || value.size() > 64)
        return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
               (character >= '0' && character <= '9') || character == '.' || character == '_' || character == '-';
    });
}

bool valid_display_name(std::string_view value)
{
    if (value.empty() || value.size() > 128)
        return false;
    return std::none_of(value.begin(), value.end(),
                        [](unsigned char character) { return character < 0x20 || character == 0x7f; });
}

bool valid_color(std::string_view value)
{
    if (value.size() != 7 || value.front() != '#')
        return false;
    return std::all_of(value.begin() + 1, value.end(), [](unsigned char character) {
        return (character >= '0' && character <= '9') || (character >= 'a' && character <= 'f') ||
               (character >= 'A' && character <= 'F');
    });
}

bool valid_asset_path(std::string_view value)
{
    if (value.empty() || value.size() > 2048 || value.front() != '/')
        return false;
    if (value.find('\0') != std::string_view::npos || value.find("/../") != std::string_view::npos ||
        value.ends_with("/.."))
        return false;
    return value.starts_with("/assets/") || value.starts_with("/recordings/");
}

bool valid_filter_kind(std::string_view value)
{
    constexpr std::array<std::string_view, 7> kinds = {
        "crop-pad", "opacity", "color-correction", "mask-blend", "lut", "scaling", "delay"};
    return std::find(kinds.begin(), kinds.end(), value) != kinds.end();
}

bool valid_scaling_resolution(std::string_view value)
{
    const std::size_t separator = value.find('x');
    if (separator == std::string_view::npos || separator == 0 || separator + 1 >= value.size() ||
        value.find('x', separator + 1) != std::string_view::npos)
        return false;
    const auto parse_dimension = [](std::string_view text) -> std::optional<unsigned long> {
        if (text.empty() || text.size() > 4 ||
            !std::all_of(text.begin(), text.end(), [](unsigned char c) { return c >= '0' && c <= '9'; }))
            return std::nullopt;
        unsigned long parsed = 0;
        for (const char character : text)
            parsed = parsed * 10 + static_cast<unsigned long>(character - '0');
        return parsed;
    };
    const auto width = parse_dimension(value.substr(0, separator));
    const auto height = parse_dimension(value.substr(separator + 1));
    return width && height && *width >= 16 && *width <= 8192 && *height >= 16 && *height <= 8192;
}

bool valid_rtsp_url(std::string_view value)
{
    constexpr std::array<std::string_view, 2> schemes = {"rtsp://", "rtsps://"};
    const auto scheme = std::find_if(schemes.begin(), schemes.end(),
                                     [value](std::string_view candidate) { return value.starts_with(candidate); });
    if (scheme == schemes.end() || value.size() > 2048)
        return false;
    const std::string_view remainder = value.substr(scheme->size());
    if (remainder.empty() || remainder.front() == '/' || remainder.front() == '?' || remainder.front() == '#')
        return false;
    const std::size_t authority_end = remainder.find_first_of("/?#");
    const std::string_view authority = remainder.substr(0, authority_end);
    const std::size_t at = authority.rfind('@');
    const std::string_view host = at == std::string_view::npos ? authority : authority.substr(at + 1);
    if (host.empty())
        return false;
    return std::none_of(value.begin(), value.end(), [](unsigned char character) {
        return character <= 0x20 || character == 0x7f;
    });
}

JsonPtr make_object()
{
    return JsonPtr(json_object());
}

bool set_new(json_t *object, const char *key, json_t *value)
{
    if (!value)
        return false;
    return json_object_set_new(object, key, value) == 0;
}

JsonPtr serialize_crop(const SceneCrop &crop)
{
    JsonPtr object = make_object();
    if (!object || !set_new(object.get(), "top", json_integer(crop.top)) ||
        !set_new(object.get(), "right", json_integer(crop.right)) ||
        !set_new(object.get(), "bottom", json_integer(crop.bottom)) ||
        !set_new(object.get(), "left", json_integer(crop.left)))
        return {};
    return object;
}

} // namespace

std::optional<std::string> validate_scene_document(const SceneDocument &document)
{
    if (document.schema_version != current_scene_schema_version)
        return "scene schemaVersion is unsupported";
    if (document.revision > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
        return "scene revision is out of range";
    if (!valid_identifier(document.id))
        return "scene id is invalid";
    if (!valid_display_name(document.name))
        return "scene name is invalid";
    if (document.canvas.width < 16 || document.canvas.width > 8192 || document.canvas.width % 2 != 0)
        return "canvas width must be an even number between 16 and 8192";
    if (document.canvas.height < 16 || document.canvas.height > 8192 || document.canvas.height % 2 != 0)
        return "canvas height must be an even number between 16 and 8192";
    if (!valid_color(document.canvas.background_color))
        return "canvas backgroundColor must use #RRGGBB";
    if (document.sources.size() > maximum_scene_sources)
        return "scene has too many sources";
    if (document.items.size() > maximum_scene_items)
        return "scene has too many items";

    std::unordered_set<std::string> source_ids;
    std::size_t browser_source_count = 0;
    for (const SceneSource &source : document.sources) {
        if (!valid_identifier(source.id))
            return "source id is invalid";
        if (!source_ids.insert(source.id).second)
            return "source ids must be unique";
        if (!valid_display_name(source.name))
            return "source name is invalid";
        if (source.kind == "rtsp") {
            if (!valid_rtsp_url(source.rtsp_url))
                return "source rtspUrl is invalid";
            if (source.transport != "tcp" && source.transport != "udp")
                return "source transport must be tcp or udp";
            if (!source.browser_url.empty() || !source.browser_css.empty())
                return "RTSP source must not contain browser-only settings";
        } else if (source.kind == "camera") {
            if (!valid_identifier(source.camera_id) || !valid_identifier(source.profile_id))
                return "camera source cameraId and profileId must be valid identifiers";
            if (source.hardware_decode != "auto" && source.hardware_decode != "on" &&
                source.hardware_decode != "off")
                return "camera source hardwareDecode must be auto, on, or off";
            if (!source.rtsp_url.empty() || !source.browser_url.empty())
                return "camera source must not contain a raw URL";
        } else if (source.kind == "browser") {
            ++browser_source_count;
            if (!parse_browser_url(source.browser_url).ok())
                return "source browser URL is invalid";
            if (source.browser_width < 16 || source.browser_width > 8192 ||
                source.browser_height < 16 || source.browser_height > 8192)
                return "browser source dimensions must be between 16 and 8192";
            if (source.browser_fps < 1 || source.browser_fps > 60)
                return "browser source fps must be between 1 and 60";
            if (source.browser_css.size() > 32768)
                return "browser source customCss exceeds the 32 KiB limit";
            if (!source.rtsp_url.empty())
                return "browser source must not contain RTSP-only settings";
        } else if (source.kind == "image" || source.kind == "media") {
            if (!valid_asset_path(source.file_path))
                return "image and media source filePath must be an absolute /assets or /recordings path";
        } else if (source.kind == "text") {
            if (source.text.empty() || source.text.size() > 8192)
                return "text source content must be between 1 and 8192 bytes";
            if (!valid_color(source.color))
                return "text source color must use #RRGGBB";
        } else if (source.kind == "color") {
            if (!valid_color(source.color))
                return "color source color must use #RRGGBB";
        } else if (source.kind == "nested") {
            if (!valid_identifier(source.nested_scene_id))
                return "nested source sceneId is invalid";
        } else {
            return "source kind must be camera, rtsp, browser, image, text, color, media, or nested";
        }
        if (!std::isfinite(source.volume) || source.volume < 0.0 || source.volume > 1.0)
            return "source volume must be between 0 and 1";
        if (source.sync_offset_ms < -10000 || source.sync_offset_ms > 10000)
            return "source syncOffsetMs must be between -10000 and 10000";
        if (source.monitoring != "off" && source.monitoring != "monitor-only" &&
            source.monitoring != "monitor-and-output")
            return "source monitoring must be off, monitor-only, or monitor-and-output";
        if (source.audio_track < 1 || source.audio_track > 6)
            return "source audioTrack must be between 1 and 6";
        if (source.filters.size() > maximum_source_filters)
            return "source has too many filters";
        std::unordered_set<std::string> filter_ids;
        for (const SceneFilter &filter : source.filters) {
            if (!valid_identifier(filter.id) || !filter_ids.insert(filter.id).second)
                return "source filter ids must be valid and unique";
            if (!valid_filter_kind(filter.kind))
                return "source filter kind is unsupported";
            if (!std::isfinite(filter.amount) || filter.amount < -10000.0 || filter.amount > 10000.0)
                return "source filter amount is out of range";
            if (filter.value.size() > 4096)
                return "source filter value exceeds the 4 KiB limit";
            if ((filter.kind == "lut" || filter.kind == "mask-blend") &&
                !valid_asset_path(filter.value))
                return "LUT and mask filter values must be absolute /assets or /recordings paths";
            if (filter.kind == "scaling" && !valid_scaling_resolution(filter.value))
                return "scaling filter value must use WIDTHxHEIGHT with dimensions between 16 and 8192";
        }
    }
    if (browser_source_count > maximum_browser_sources)
        return "scene has too many browser sources";

    std::unordered_set<std::string> item_ids;
    std::vector<bool> z_indexes(document.items.size(), false);
    for (const SceneItem &item : document.items) {
        if (!valid_identifier(item.id))
            return "item id is invalid";
        if (!item_ids.insert(item.id).second)
            return "item ids must be unique";
        if (!source_ids.contains(item.source_id))
            return "item sourceId must reference an existing source";
        if (item.x < -32768 || item.x > 32768 || item.y < -32768 || item.y > 32768)
            return "item coordinates are out of range";
        if (item.width < 1 || item.width > 8192 || item.height < 1 || item.height > 8192)
            return "item dimensions are out of range";
        if (item.scale_mode != "contain" && item.scale_mode != "cover" && item.scale_mode != "stretch")
            return "item scaleMode must be contain, cover, or stretch";
        const std::array<int, 4> crop_values = {item.crop.top, item.crop.right, item.crop.bottom, item.crop.left};
        if (std::any_of(crop_values.begin(), crop_values.end(),
                        [](int value) { return value < 0 || value > 8192; }))
            return "item crop values are out of range";
        if (item.z_index < 0 || static_cast<std::size_t>(item.z_index) >= document.items.size() ||
            z_indexes[static_cast<std::size_t>(item.z_index)])
            return "item zIndex values must be unique and contiguous";
        z_indexes[static_cast<std::size_t>(item.z_index)] = true;
        if (!item.group_id.empty() && !valid_identifier(item.group_id))
            return "item groupId is invalid";
        if (!std::isfinite(item.rotation_degrees) || item.rotation_degrees < -360.0 ||
            item.rotation_degrees > 360.0)
            return "item rotation must be between -360 and 360 degrees";
        if (!std::isfinite(item.opacity) || item.opacity < 0.0 || item.opacity > 1.0)
            return "item opacity must be between 0 and 1";
        if (item.blend_mode != "normal" && item.blend_mode != "add" &&
            item.blend_mode != "multiply" && item.blend_mode != "screen")
            return "item blendMode is unsupported";
    }
    return std::nullopt;
}

SceneParseResult parse_scene_json(std::string_view input)
{
    if (input.empty())
        return parse_failure("scene JSON must not be empty");
    if (input.size() > maximum_scene_json_bytes)
        return parse_failure("scene JSON exceeds the one MiB limit");

    json_error_t json_error{};
    JsonPtr root(json_loadb(input.data(), input.size(), JSON_REJECT_DUPLICATES, &json_error));
    if (!root)
        return parse_failure("invalid scene JSON at line " + std::to_string(json_error.line) + " column " +
                             std::to_string(json_error.column));
    if (!json_is_object(root.get()))
        return parse_failure("scene JSON root must be an object");
    if (!has_only_fields(root.get(), {"schemaVersion", "revision", "id", "name", "canvas", "sources", "items"}))
        return parse_failure("scene JSON root contains an unsupported field");

    SceneDocument document;
    std::string error;
    if (!read_integer(root.get(), "schemaVersion", current_scene_schema_version, current_scene_schema_version,
                      document.schema_version, error, "scene"))
        return parse_failure(std::move(error));

    json_t *revision = json_object_get(root.get(), "revision");
    if (!json_is_integer(revision) || json_integer_value(revision) < 0)
        return parse_failure("scene revision must be a non-negative integer");
    document.revision = static_cast<std::uint64_t>(json_integer_value(revision));
    if (!read_string(root.get(), "id", document.id, 64, error, "scene") ||
        !read_string(root.get(), "name", document.name, 128, error, "scene"))
        return parse_failure(std::move(error));

    json_t *canvas = json_object_get(root.get(), "canvas");
    if (!json_is_object(canvas) || !has_only_fields(canvas, {"width", "height", "backgroundColor"}))
        return parse_failure("scene canvas is invalid or contains an unsupported field");
    if (!read_integer(canvas, "width", 16, 8192, document.canvas.width, error, "canvas") ||
        !read_integer(canvas, "height", 16, 8192, document.canvas.height, error, "canvas") ||
        !read_string(canvas, "backgroundColor", document.canvas.background_color, 7, error, "canvas"))
        return parse_failure(std::move(error));

    json_t *sources = json_object_get(root.get(), "sources");
    if (!json_is_array(sources) || json_array_size(sources) > maximum_scene_sources)
        return parse_failure("scene sources must be an array within the configured limit");
    document.sources.reserve(json_array_size(sources));
    std::size_t index = 0;
    json_t *source_object = nullptr;
    json_array_foreach(sources, index, source_object)
    {
        if (!json_is_object(source_object))
            return parse_failure("source entry must be an object");
        SceneSource source;
        if (!read_string(source_object, "id", source.id, 64, error, "source") ||
            !read_string(source_object, "kind", source.kind, 16, error, "source") ||
            !read_string(source_object, "name", source.name, 128, error, "source") ||
            !read_boolean(source_object, "muted", source.muted, error, "source") ||
            !read_number(source_object, "volume", source.volume, error, "source") ||
            !read_integer(source_object, "syncOffsetMs", -10000, 10000, source.sync_offset_ms, error,
                          "source") ||
            !read_string(source_object, "monitoring", source.monitoring, 24, error, "source") ||
            !read_integer(source_object, "audioTrack", 1, 6, source.audio_track, error, "source"))
            return parse_failure(std::move(error));
        if (source.kind == "rtsp") {
            if (!has_only_fields(source_object,
                                 {"id", "kind", "name", "rtspUrl", "transport", "muted", "volume",
                                  "syncOffsetMs", "monitoring", "audioTrack", "filters"}))
                return parse_failure("RTSP source contains an unsupported field");
            if (!read_string(source_object, "rtspUrl", source.rtsp_url, 2048, error, "source") ||
                !read_string(source_object, "transport", source.transport, 4, error, "source"))
                return parse_failure(std::move(error));
        } else if (source.kind == "camera") {
            if (!has_only_fields(source_object,
                                 {"id", "kind", "name", "cameraId", "profileId", "hardwareDecode",
                                  "muted", "volume", "syncOffsetMs", "monitoring", "audioTrack", "filters"}))
                return parse_failure("camera source contains an unsupported field");
            source.transport.clear();
            if (!read_string(source_object, "cameraId", source.camera_id, 64, error, "source") ||
                !read_string(source_object, "profileId", source.profile_id, 64, error, "source") ||
                !read_string(source_object, "hardwareDecode", source.hardware_decode, 4, error, "source"))
                return parse_failure(std::move(error));
        } else if (source.kind == "browser") {
            if (!has_only_fields(source_object,
                                 {"id", "kind", "name", "url", "width", "height", "fps", "customCss",
                                  "shutdownWhenHidden", "restartWhenActive", "muted", "volume",
                                  "syncOffsetMs", "monitoring", "audioTrack", "filters"}))
                return parse_failure("browser source contains an unsupported field");
            source.transport.clear();
            if (!read_string(source_object, "url", source.browser_url, 2048, error, "source") ||
                !read_integer(source_object, "width", 16, 8192, source.browser_width, error, "source") ||
                !read_integer(source_object, "height", 16, 8192, source.browser_height, error, "source") ||
                !read_integer(source_object, "fps", 1, 60, source.browser_fps, error, "source") ||
                !read_string_allow_empty(source_object, "customCss", source.browser_css, 32768, error,
                                         "source") ||
                !read_boolean(source_object, "shutdownWhenHidden", source.shutdown_when_hidden, error,
                              "source") ||
                !read_boolean(source_object, "restartWhenActive", source.restart_when_active, error,
                              "source"))
                return parse_failure(std::move(error));
        } else if (source.kind == "image") {
            if (!has_only_fields(source_object,
                                 {"id", "kind", "name", "filePath", "muted", "volume",
                                  "syncOffsetMs", "monitoring", "audioTrack", "filters"}) ||
                !read_string(source_object, "filePath", source.file_path, 2048, error, "source"))
                return parse_failure("image source is invalid or contains an unsupported field");
        } else if (source.kind == "media") {
            if (!has_only_fields(source_object,
                                 {"id", "kind", "name", "filePath", "loop", "muted", "volume",
                                  "syncOffsetMs", "monitoring", "audioTrack", "filters"}) ||
                !read_string(source_object, "filePath", source.file_path, 2048, error, "source") ||
                !read_boolean(source_object, "loop", source.loop, error, "source"))
                return parse_failure("media source is invalid or contains an unsupported field");
        } else if (source.kind == "text") {
            if (!has_only_fields(source_object,
                                 {"id", "kind", "name", "text", "color", "muted", "volume",
                                  "syncOffsetMs", "monitoring", "audioTrack", "filters"}) ||
                !read_string(source_object, "text", source.text, 8192, error, "source") ||
                !read_string(source_object, "color", source.color, 7, error, "source"))
                return parse_failure("text source is invalid or contains an unsupported field");
        } else if (source.kind == "color") {
            if (!has_only_fields(source_object,
                                 {"id", "kind", "name", "color", "muted", "volume",
                                  "syncOffsetMs", "monitoring", "audioTrack", "filters"}) ||
                !read_string(source_object, "color", source.color, 7, error, "source"))
                return parse_failure("color source is invalid or contains an unsupported field");
        } else if (source.kind == "nested") {
            if (!has_only_fields(source_object,
                                 {"id", "kind", "name", "sceneId", "muted", "volume",
                                  "syncOffsetMs", "monitoring", "audioTrack", "filters"}) ||
                !read_string(source_object, "sceneId", source.nested_scene_id, 64, error, "source"))
                return parse_failure("nested source is invalid or contains an unsupported field");
        } else {
            return parse_failure("source kind is unsupported");
        }

        json_t *filters = json_object_get(source_object, "filters");
        if (filters != nullptr &&
            (!json_is_array(filters) || json_array_size(filters) > maximum_source_filters))
            return parse_failure("source filters must be an array within the configured limit");
        std::size_t filter_index = 0;
        json_t *filter_object = nullptr;
        json_array_foreach(filters, filter_index, filter_object)
        {
            if (!json_is_object(filter_object) ||
                !has_only_fields(filter_object, {"id", "kind", "enabled", "amount", "value"}))
                return parse_failure("source filter is invalid or contains an unsupported field");
            SceneFilter filter;
            if (!read_string(filter_object, "id", filter.id, 64, error, "filter") ||
                !read_string(filter_object, "kind", filter.kind, 32, error, "filter") ||
                !read_boolean(filter_object, "enabled", filter.enabled, error, "filter") ||
                !read_number(filter_object, "amount", filter.amount, error, "filter") ||
                !read_string_allow_empty(filter_object, "value", filter.value, 4096, error, "filter"))
                return parse_failure(std::move(error));
            source.filters.push_back(std::move(filter));
        }
        document.sources.push_back(std::move(source));
    }

    json_t *items = json_object_get(root.get(), "items");
    if (!json_is_array(items) || json_array_size(items) > maximum_scene_items)
        return parse_failure("scene items must be an array within the configured limit");
    document.items.reserve(json_array_size(items));
    json_t *item_object = nullptr;
    json_array_foreach(items, index, item_object)
    {
        if (!json_is_object(item_object) ||
            !has_only_fields(item_object,
                             {"id", "sourceId", "x", "y", "width", "height", "scaleMode", "crop", "zIndex",
                              "visible", "locked", "groupId", "rotation", "opacity", "blendMode"}))
            return parse_failure("item entry is invalid or contains an unsupported field");
        SceneItem item;
        if (!read_string(item_object, "id", item.id, 64, error, "item") ||
            !read_string(item_object, "sourceId", item.source_id, 64, error, "item") ||
            !read_integer(item_object, "x", -32768, 32768, item.x, error, "item") ||
            !read_integer(item_object, "y", -32768, 32768, item.y, error, "item") ||
            !read_integer(item_object, "width", 1, 8192, item.width, error, "item") ||
            !read_integer(item_object, "height", 1, 8192, item.height, error, "item") ||
            !read_integer(item_object, "zIndex", 0, static_cast<int>(maximum_scene_items - 1), item.z_index,
                          error, "item") ||
            !read_boolean(item_object, "visible", item.visible, error, "item"))
            return parse_failure(std::move(error));

        if ((json_object_get(item_object, "locked") != nullptr &&
             !read_boolean(item_object, "locked", item.locked, error, "item")) ||
            (json_object_get(item_object, "groupId") != nullptr &&
             !read_string_allow_empty(item_object, "groupId", item.group_id, 64, error, "item")) ||
            (json_object_get(item_object, "rotation") != nullptr &&
             !read_number(item_object, "rotation", item.rotation_degrees, error, "item")) ||
            (json_object_get(item_object, "opacity") != nullptr &&
             !read_number(item_object, "opacity", item.opacity, error, "item")) ||
            (json_object_get(item_object, "blendMode") != nullptr &&
             !read_string(item_object, "blendMode", item.blend_mode, 16, error, "item")))
            return parse_failure(std::move(error));

        if (json_object_get(item_object, "scaleMode") != nullptr &&
            !read_string(item_object, "scaleMode", item.scale_mode, 16, error, "item"))
            return parse_failure(std::move(error));

        json_t *crop = json_object_get(item_object, "crop");
        if (!json_is_object(crop) || !has_only_fields(crop, {"top", "right", "bottom", "left"}))
            return parse_failure("item crop is invalid or contains an unsupported field");
        if (!read_integer(crop, "top", 0, 8192, item.crop.top, error, "crop") ||
            !read_integer(crop, "right", 0, 8192, item.crop.right, error, "crop") ||
            !read_integer(crop, "bottom", 0, 8192, item.crop.bottom, error, "crop") ||
            !read_integer(crop, "left", 0, 8192, item.crop.left, error, "crop"))
            return parse_failure(std::move(error));
        document.items.push_back(std::move(item));
    }

    if (const auto validation_error = validate_scene_document(document))
        return parse_failure(*validation_error);
    SceneParseResult result;
    result.document = std::move(document);
    return result;
}

SceneSerializeResult serialize_scene_json(const SceneDocument &document, SceneJsonView view, bool pretty)
{
    if (const auto validation_error = validate_scene_document(document))
        return serialize_failure(*validation_error);

    JsonPtr root = make_object();
    JsonPtr canvas = make_object();
    JsonPtr sources(json_array());
    JsonPtr items(json_array());
    if (!root || !canvas || !sources || !items)
        return serialize_failure("could not allocate scene JSON");

    if (!set_new(root.get(), "schemaVersion", json_integer(document.schema_version)) ||
        !set_new(root.get(), "revision", json_integer(static_cast<json_int_t>(document.revision))) ||
        !set_new(root.get(), "id", json_stringn(document.id.data(), document.id.size())) ||
        !set_new(root.get(), "name", json_stringn(document.name.data(), document.name.size())) ||
        !set_new(canvas.get(), "width", json_integer(document.canvas.width)) ||
        !set_new(canvas.get(), "height", json_integer(document.canvas.height)) ||
        !set_new(canvas.get(), "backgroundColor",
                 json_stringn(document.canvas.background_color.data(), document.canvas.background_color.size())))
        return serialize_failure("could not build scene JSON");
    if (!set_new(root.get(), "canvas", canvas.release()))
        return serialize_failure("could not build scene JSON");

    for (const SceneSource &source : document.sources) {
        JsonPtr object = make_object();
        JsonPtr filters(json_array());
        if (!object || !set_new(object.get(), "id", json_stringn(source.id.data(), source.id.size())) ||
            !set_new(object.get(), "kind", json_stringn(source.kind.data(), source.kind.size())) ||
            !set_new(object.get(), "name", json_stringn(source.name.data(), source.name.size())) ||
            !set_new(object.get(), "muted", json_boolean(source.muted)) ||
            !set_new(object.get(), "volume", json_real(source.volume)) ||
            !set_new(object.get(), "syncOffsetMs", json_integer(source.sync_offset_ms)) ||
            !set_new(object.get(), "monitoring",
                     json_stringn(source.monitoring.data(), source.monitoring.size())) ||
            !set_new(object.get(), "audioTrack", json_integer(source.audio_track)) || !filters)
            return serialize_failure("could not build source JSON");
        for (const SceneFilter &filter : source.filters) {
            JsonPtr filter_object = make_object();
            if (!filter_object ||
                !set_new(filter_object.get(), "id", json_stringn(filter.id.data(), filter.id.size())) ||
                !set_new(filter_object.get(), "kind", json_stringn(filter.kind.data(), filter.kind.size())) ||
                !set_new(filter_object.get(), "enabled", json_boolean(filter.enabled)) ||
                !set_new(filter_object.get(), "amount", json_real(filter.amount)) ||
                !set_new(filter_object.get(), "value", json_stringn(filter.value.data(), filter.value.size())) ||
                json_array_append_new(filters.get(), filter_object.release()) != 0)
                return serialize_failure("could not build source filter JSON");
        }
        if (!set_new(object.get(), "filters", filters.release()))
            return serialize_failure("could not build source filter JSON");
        if (source.kind == "rtsp") {
            const std::string safe_url = view == SceneJsonView::public_api
                                             ? redact_rtsp_credentials(source.rtsp_url)
                                             : source.rtsp_url;
            if (!set_new(object.get(), "rtspUrl", json_stringn(safe_url.data(), safe_url.size())) ||
                !set_new(object.get(), "transport",
                         json_stringn(source.transport.data(), source.transport.size())))
                return serialize_failure("could not build RTSP source JSON");
        } else if (source.kind == "camera") {
            if (!set_new(object.get(), "cameraId",
                         json_stringn(source.camera_id.data(), source.camera_id.size())) ||
                !set_new(object.get(), "profileId",
                         json_stringn(source.profile_id.data(), source.profile_id.size())) ||
                !set_new(object.get(), "hardwareDecode",
                         json_stringn(source.hardware_decode.data(), source.hardware_decode.size())))
                return serialize_failure("could not build camera source JSON");
        } else if (source.kind == "browser") {
            const std::string safe_url = view == SceneJsonView::public_api
                                             ? redact_browser_url(source.browser_url)
                                             : source.browser_url;
            if (!set_new(object.get(), "url", json_stringn(safe_url.data(), safe_url.size())) ||
                !set_new(object.get(), "width", json_integer(source.browser_width)) ||
                !set_new(object.get(), "height", json_integer(source.browser_height)) ||
                !set_new(object.get(), "fps", json_integer(source.browser_fps)) ||
                !set_new(object.get(), "customCss",
                         json_stringn(source.browser_css.data(), source.browser_css.size())) ||
                !set_new(object.get(), "shutdownWhenHidden", json_boolean(source.shutdown_when_hidden)) ||
                !set_new(object.get(), "restartWhenActive", json_boolean(source.restart_when_active)))
                return serialize_failure("could not build browser source JSON");
        } else if (source.kind == "image") {
            if (!set_new(object.get(), "filePath",
                         json_stringn(source.file_path.data(), source.file_path.size())))
                return serialize_failure("could not build image source JSON");
        } else if (source.kind == "media") {
            if (!set_new(object.get(), "filePath",
                         json_stringn(source.file_path.data(), source.file_path.size())) ||
                !set_new(object.get(), "loop", json_boolean(source.loop)))
                return serialize_failure("could not build media source JSON");
        } else if (source.kind == "text") {
            if (!set_new(object.get(), "text", json_stringn(source.text.data(), source.text.size())) ||
                !set_new(object.get(), "color", json_stringn(source.color.data(), source.color.size())))
                return serialize_failure("could not build text source JSON");
        } else if (source.kind == "color") {
            if (!set_new(object.get(), "color", json_stringn(source.color.data(), source.color.size())))
                return serialize_failure("could not build color source JSON");
        } else if (source.kind == "nested") {
            if (!set_new(object.get(), "sceneId",
                         json_stringn(source.nested_scene_id.data(), source.nested_scene_id.size())))
                return serialize_failure("could not build nested source JSON");
        }
        if (json_array_append_new(sources.get(), object.release()) != 0)
            return serialize_failure("could not build source JSON");
    }
    if (!set_new(root.get(), "sources", sources.release()))
        return serialize_failure("could not build scene JSON");

    for (const SceneItem &item : document.items) {
        JsonPtr object = make_object();
        JsonPtr crop = serialize_crop(item.crop);
        if (!object || !crop || !set_new(object.get(), "id", json_stringn(item.id.data(), item.id.size())) ||
            !set_new(object.get(), "sourceId", json_stringn(item.source_id.data(), item.source_id.size())) ||
            !set_new(object.get(), "x", json_integer(item.x)) ||
            !set_new(object.get(), "y", json_integer(item.y)) ||
            !set_new(object.get(), "width", json_integer(item.width)) ||
            !set_new(object.get(), "height", json_integer(item.height)) ||
            !set_new(object.get(), "scaleMode", json_stringn(item.scale_mode.data(), item.scale_mode.size())) ||
            !set_new(object.get(), "crop", crop.release()) ||
            !set_new(object.get(), "zIndex", json_integer(item.z_index)) ||
            !set_new(object.get(), "visible", json_boolean(item.visible)) ||
            !set_new(object.get(), "locked", json_boolean(item.locked)) ||
            !set_new(object.get(), "groupId", json_stringn(item.group_id.data(), item.group_id.size())) ||
            !set_new(object.get(), "rotation", json_real(item.rotation_degrees)) ||
            !set_new(object.get(), "opacity", json_real(item.opacity)) ||
            !set_new(object.get(), "blendMode",
                     json_stringn(item.blend_mode.data(), item.blend_mode.size())) ||
            json_array_append_new(items.get(), object.release()) != 0)
            return serialize_failure("could not build item JSON");
    }
    if (!set_new(root.get(), "items", items.release()))
        return serialize_failure("could not build scene JSON");

    const std::size_t flags = JSON_SORT_KEYS | JSON_REAL_PRECISION(6) | (pretty ? JSON_INDENT(2) : JSON_COMPACT);
    char *encoded = json_dumps(root.get(), flags);
    if (!encoded)
        return serialize_failure("could not encode scene JSON");
    SceneSerializeResult result;
    result.json.assign(encoded);
    std::free(encoded);
    if (pretty)
        result.json.push_back('\n');
    return result;
}

} // namespace webobs
