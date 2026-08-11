#include "webobs/scene_document.hpp"

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
    for (const SceneSource &source : document.sources) {
        if (!valid_identifier(source.id))
            return "source id is invalid";
        if (!source_ids.insert(source.id).second)
            return "source ids must be unique";
        if (!valid_display_name(source.name))
            return "source name is invalid";
        if (!valid_rtsp_url(source.rtsp_url))
            return "source rtspUrl is invalid";
        if (source.transport != "tcp" && source.transport != "udp")
            return "source transport must be tcp or udp";
        if (!std::isfinite(source.volume) || source.volume < 0.0 || source.volume > 1.0)
            return "source volume must be between 0 and 1";
    }

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
        const std::array<int, 4> crop_values = {item.crop.top, item.crop.right, item.crop.bottom, item.crop.left};
        if (std::any_of(crop_values.begin(), crop_values.end(),
                        [](int value) { return value < 0 || value > 8192; }))
            return "item crop values are out of range";
        if (item.z_index < 0 || static_cast<std::size_t>(item.z_index) >= document.items.size() ||
            z_indexes[static_cast<std::size_t>(item.z_index)])
            return "item zIndex values must be unique and contiguous";
        z_indexes[static_cast<std::size_t>(item.z_index)] = true;
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
        if (!json_is_object(source_object) ||
            !has_only_fields(source_object,
                             {"id", "kind", "name", "rtspUrl", "transport", "muted", "volume"}))
            return parse_failure("source entry is invalid or contains an unsupported field");
        std::string kind;
        SceneSource source;
        if (!read_string(source_object, "id", source.id, 64, error, "source") ||
            !read_string(source_object, "kind", kind, 16, error, "source") ||
            !read_string(source_object, "name", source.name, 128, error, "source") ||
            !read_string(source_object, "rtspUrl", source.rtsp_url, 2048, error, "source") ||
            !read_string(source_object, "transport", source.transport, 4, error, "source") ||
            !read_boolean(source_object, "muted", source.muted, error, "source") ||
            !read_number(source_object, "volume", source.volume, error, "source"))
            return parse_failure(std::move(error));
        if (kind != "rtsp")
            return parse_failure("source kind must be rtsp in M1");
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
                             {"id", "sourceId", "x", "y", "width", "height", "crop", "zIndex", "visible"}))
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
        const std::string safe_url =
            view == SceneJsonView::public_api ? redact_rtsp_credentials(source.rtsp_url) : source.rtsp_url;
        if (!object || !set_new(object.get(), "id", json_stringn(source.id.data(), source.id.size())) ||
            !set_new(object.get(), "kind", json_string("rtsp")) ||
            !set_new(object.get(), "name", json_stringn(source.name.data(), source.name.size())) ||
            !set_new(object.get(), "rtspUrl", json_stringn(safe_url.data(), safe_url.size())) ||
            !set_new(object.get(), "transport", json_stringn(source.transport.data(), source.transport.size())) ||
            !set_new(object.get(), "muted", json_boolean(source.muted)) ||
            !set_new(object.get(), "volume", json_real(source.volume)) ||
            json_array_append_new(sources.get(), object.release()) != 0)
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
            !set_new(object.get(), "crop", crop.release()) ||
            !set_new(object.get(), "zIndex", json_integer(item.z_index)) ||
            !set_new(object.get(), "visible", json_boolean(item.visible)) ||
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
