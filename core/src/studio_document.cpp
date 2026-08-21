#include "webobs/studio_document.hpp"

#include <jansson.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <memory>
#include <unordered_map>
#include <unordered_set>

namespace webobs {
namespace {

struct JsonDeleter {
    void operator()(json_t *value) const { json_decref(value); }
};
using JsonPtr = std::unique_ptr<json_t, JsonDeleter>;

bool valid_identifier(std::string_view value)
{
    if (value.empty() || value.size() > 64)
        return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return std::isalnum(character) || character == '.' || character == '_' || character == '-';
    });
}

bool only_fields(json_t *object, std::initializer_list<std::string_view> allowed)
{
    const char *key = nullptr;
    json_t *value = nullptr;
    json_object_foreach(object, key, value)
    {
        (void)value;
        if (std::none_of(allowed.begin(), allowed.end(),
                         [key](std::string_view candidate) { return candidate == key; }))
            return false;
    }
    return true;
}

StudioParseResult parse_failure(std::string error)
{
    StudioParseResult result;
    result.error = std::move(error);
    return result;
}

SceneSerializeResult serialize_failure(std::string error)
{
    SceneSerializeResult result;
    result.error = std::move(error);
    return result;
}

const SceneDocument *find_scene(const StudioDocument &document, std::string_view id)
{
    const auto found = std::find_if(document.scenes.begin(), document.scenes.end(),
                                    [id](const SceneDocument &scene) { return scene.id == id; });
    return found == document.scenes.end() ? nullptr : &*found;
}

bool visit_nested(const StudioDocument &document, const SceneDocument &scene, int depth,
                  std::unordered_set<std::string> &stack, std::string &error)
{
    if (depth > 2) {
        error = "nested scenes are limited to two levels";
        return false;
    }
    if (!stack.insert(scene.id).second) {
        error = "nested scenes must not contain a cycle";
        return false;
    }
    for (const SceneSource &source : scene.sources) {
        if (source.kind != "nested")
            continue;
        const SceneDocument *child = find_scene(document, source.nested_scene_id);
        if (!child) {
            error = "nested source references a missing scene";
            stack.erase(scene.id);
            return false;
        }
        if (!visit_nested(document, *child, depth + 1, stack, error)) {
            stack.erase(scene.id);
            return false;
        }
    }
    stack.erase(scene.id);
    return true;
}

struct FlattenContext {
    SceneDocument result;
    std::unordered_map<std::string, std::string> source_ids;
};

std::string mapped_source_id(FlattenContext &context, const SceneSource &source, std::string_view path)
{
    const SceneSerializeResult encoded_scene = [&] {
        SceneDocument one;
        one.sources.push_back(source);
        return serialize_scene_json(one, SceneJsonView::persistence, false);
    }();
    const std::string key = encoded_scene.ok() ? encoded_scene.json : std::string(path) + source.id;
    if (const auto existing = context.source_ids.find(key); existing != context.source_ids.end())
        return existing->second;
    std::string id = std::string(path) + source.id;
    std::replace(id.begin(), id.end(), '/', '.');
    if (id.size() > 64)
        id = "source-" + std::to_string(context.result.sources.size());
    SceneSource copy = source;
    copy.id = id;
    context.result.sources.push_back(std::move(copy));
    context.source_ids.emplace(key, id);
    return id;
}

bool flatten_into(const StudioDocument &studio, const SceneDocument &scene, const SceneItem *parent,
                  std::string path, int depth, FlattenContext &context, std::string &error)
{
    std::vector<const SceneItem *> ordered;
    for (const SceneItem &item : scene.items)
        ordered.push_back(&item);
    std::sort(ordered.begin(), ordered.end(), [](const SceneItem *left, const SceneItem *right) {
        return left->z_index < right->z_index;
    });

    for (const SceneItem *item : ordered) {
        const auto source = std::find_if(scene.sources.begin(), scene.sources.end(), [item](const SceneSource &entry) {
            return entry.id == item->source_id;
        });
        if (source == scene.sources.end()) {
            error = "scene item references a missing source while flattening";
            return false;
        }
        SceneItem transformed = *item;
        if (parent) {
            const double scale_x = static_cast<double>(parent->width) / scene.canvas.width;
            const double scale_y = static_cast<double>(parent->height) / scene.canvas.height;
            transformed.x = parent->x + static_cast<int>(std::lround(item->x * scale_x));
            transformed.y = parent->y + static_cast<int>(std::lround(item->y * scale_y));
            transformed.width = std::max(1, static_cast<int>(std::lround(item->width * scale_x)));
            transformed.height = std::max(1, static_cast<int>(std::lround(item->height * scale_y)));
            transformed.visible = parent->visible && item->visible;
            transformed.locked = parent->locked || item->locked;
            transformed.rotation_degrees += parent->rotation_degrees;
            transformed.opacity *= parent->opacity;
            if (parent->blend_mode != "normal")
                transformed.blend_mode = parent->blend_mode;
            if (transformed.group_id.empty())
                transformed.group_id = parent->group_id;
        }
        transformed.id = path + item->id;
        std::replace(transformed.id.begin(), transformed.id.end(), '/', '.');
        if (transformed.id.size() > 64)
            transformed.id = "item-" + std::to_string(context.result.items.size());

        if (source->kind == "nested") {
            if (depth >= 2) {
                error = "nested scenes are limited to two levels";
                return false;
            }
            const SceneDocument *child = find_scene(studio, source->nested_scene_id);
            if (!child || !flatten_into(studio, *child, &transformed,
                                        path + source->nested_scene_id + ".", depth + 1, context, error))
                return false;
            continue;
        }

        transformed.source_id = mapped_source_id(context, *source, path);
        transformed.z_index = static_cast<int>(context.result.items.size());
        context.result.items.push_back(std::move(transformed));
    }
    return true;
}

} // namespace

std::optional<std::string> validate_studio_document(const StudioDocument &document)
{
    if (document.schema_version != current_studio_schema_version)
        return "studio schemaVersion is unsupported";
    if (document.revision > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
        return "studio revision is out of range";
    if (document.scenes.empty() || document.scenes.size() > maximum_studio_scenes)
        return "studio must contain between one and 64 scenes";
    if (!valid_identifier(document.program_scene_id) || !valid_identifier(document.preview_scene_id))
        return "studio Program and Preview scene ids are invalid";
    if (document.transition.kind != "cut" && document.transition.kind != "fade")
        return "studio transition must be cut or fade";
    if (document.transition.duration_ms < 0 || document.transition.duration_ms > 10000)
        return "studio transition duration must be between 0 and 10000 ms";

    std::unordered_set<std::string> ids;
    int width = 0;
    int height = 0;
    for (const SceneDocument &scene : document.scenes) {
        if (const auto scene_error = validate_scene_document(scene))
            return "studio scene " + scene.id + " is invalid: " + *scene_error;
        if (!ids.insert(scene.id).second)
            return "studio scene ids must be unique";
        if (width == 0) {
            width = scene.canvas.width;
            height = scene.canvas.height;
        } else if (scene.canvas.width != width || scene.canvas.height != height) {
            return "all studio scenes must use the same canvas dimensions";
        }
    }
    if (!ids.contains(document.program_scene_id) || !ids.contains(document.preview_scene_id))
        return "studio Program and Preview must reference existing scenes";
    for (const SceneDocument &scene : document.scenes) {
        std::unordered_set<std::string> stack;
        std::string error;
        if (!visit_nested(document, scene, 0, stack, error))
            return error;
    }
    return std::nullopt;
}

StudioParseResult parse_studio_json(std::string_view input)
{
    if (input.empty() || input.size() > maximum_scene_json_bytes)
        return parse_failure("studio JSON is empty or exceeds the one MiB limit");
    json_error_t json_error{};
    JsonPtr root(json_loadb(input.data(), input.size(), JSON_REJECT_DUPLICATES, &json_error));
    if (!root || !json_is_object(root.get()))
        return parse_failure("invalid studio JSON");
    if (!only_fields(root.get(), {"schemaVersion", "revision", "programSceneId", "previewSceneId",
                                  "transition", "scenes"}))
        return parse_failure("studio JSON contains an unsupported field");
    StudioDocument document;
    json_t *schema = json_object_get(root.get(), "schemaVersion");
    json_t *revision = json_object_get(root.get(), "revision");
    json_t *program = json_object_get(root.get(), "programSceneId");
    json_t *preview = json_object_get(root.get(), "previewSceneId");
    json_t *transition = json_object_get(root.get(), "transition");
    json_t *scenes = json_object_get(root.get(), "scenes");
    if (!json_is_integer(schema) || json_integer_value(schema) != current_studio_schema_version ||
        !json_is_integer(revision) || json_integer_value(revision) < 0 || !json_is_string(program) ||
        !json_is_string(preview) || !json_is_object(transition) ||
        !only_fields(transition, {"kind", "durationMs"}) || !json_is_array(scenes) ||
        json_array_size(scenes) > maximum_studio_scenes)
        return parse_failure("studio JSON fields are invalid");
    json_t *kind = json_object_get(transition, "kind");
    json_t *duration = json_object_get(transition, "durationMs");
    if (!json_is_string(kind) || !json_is_integer(duration))
        return parse_failure("studio transition is invalid");
    document.revision = static_cast<std::uint64_t>(json_integer_value(revision));
    document.program_scene_id = json_string_value(program);
    document.preview_scene_id = json_string_value(preview);
    document.transition.kind = json_string_value(kind);
    document.transition.duration_ms = static_cast<int>(json_integer_value(duration));

    std::size_t index = 0;
    json_t *scene = nullptr;
    json_array_foreach(scenes, index, scene)
    {
        char *encoded = json_dumps(scene, JSON_COMPACT | JSON_SORT_KEYS | JSON_REAL_PRECISION(6));
        if (!encoded)
            return parse_failure("could not decode a studio scene");
        const std::string scene_json(encoded);
        std::free(encoded);
        SceneParseResult parsed = parse_scene_json(scene_json);
        if (!parsed.ok())
            return parse_failure("studio contains an invalid scene: " + parsed.error);
        document.scenes.push_back(std::move(*parsed.document));
    }
    if (const auto validation_error = validate_studio_document(document))
        return parse_failure(*validation_error);
    StudioParseResult result;
    result.document = std::move(document);
    return result;
}

SceneSerializeResult serialize_studio_json(const StudioDocument &document, SceneJsonView view, bool pretty)
{
    if (const auto validation_error = validate_studio_document(document))
        return serialize_failure(*validation_error);
    JsonPtr root(json_object());
    JsonPtr transition(json_object());
    JsonPtr scenes(json_array());
    if (!root || !transition || !scenes)
        return serialize_failure("could not allocate studio JSON");
    if (json_object_set_new(root.get(), "schemaVersion", json_integer(document.schema_version)) != 0 ||
        json_object_set_new(root.get(), "revision", json_integer(document.revision)) != 0 ||
        json_object_set_new(root.get(), "programSceneId", json_string(document.program_scene_id.c_str())) != 0 ||
        json_object_set_new(root.get(), "previewSceneId", json_string(document.preview_scene_id.c_str())) != 0 ||
        json_object_set_new(transition.get(), "kind", json_string(document.transition.kind.c_str())) != 0 ||
        json_object_set_new(transition.get(), "durationMs", json_integer(document.transition.duration_ms)) != 0 ||
        json_object_set_new(root.get(), "transition", transition.release()) != 0)
        return serialize_failure("could not build studio JSON");
    for (const SceneDocument &scene : document.scenes) {
        const SceneSerializeResult encoded = serialize_scene_json(scene, view, false);
        if (!encoded.ok())
            return serialize_failure(encoded.error);
        json_error_t error{};
        json_t *scene_value = json_loadb(encoded.json.data(), encoded.json.size(), JSON_REJECT_DUPLICATES, &error);
        if (!scene_value || json_array_append_new(scenes.get(), scene_value) != 0) {
            return serialize_failure("could not build studio scene JSON");
        }
    }
    if (json_object_set_new(root.get(), "scenes", scenes.release()) != 0)
        return serialize_failure("could not build studio JSON");
    const std::size_t flags = JSON_SORT_KEYS | JSON_REAL_PRECISION(6) |
                              (pretty ? JSON_INDENT(2) : JSON_COMPACT);
    char *encoded = json_dumps(root.get(), flags);
    if (!encoded)
        return serialize_failure("could not encode studio JSON");
    SceneSerializeResult result;
    result.json = encoded;
    std::free(encoded);
    if (pretty)
        result.json.push_back('\n');
    return result;
}

StudioFlattenResult flatten_studio_scene(const StudioDocument &document, std::string_view scene_id)
{
    StudioFlattenResult result;
    if (const auto validation_error = validate_studio_document(document)) {
        result.error = *validation_error;
        return result;
    }
    const SceneDocument *scene = find_scene(document, scene_id);
    if (!scene) {
        result.error = "requested studio scene does not exist";
        return result;
    }
    FlattenContext context;
    context.result.schema_version = current_scene_schema_version;
    context.result.revision = document.revision;
    context.result.id = scene->id;
    context.result.name = scene->name;
    context.result.canvas = scene->canvas;
    if (!flatten_into(document, *scene, nullptr, scene->id + ".", 0, context, result.error))
        return result;
    if (const auto error = validate_scene_document(context.result)) {
        result.error = "flattened scene is invalid: " + *error;
        return result;
    }
    result.document = std::move(context.result);
    return result;
}

SceneCapability analyze_scene_capability(const SceneDocument &document,
                                         PlaybackCompositionMode requested)
{
    SceneCapability result;
    result.requested = requested;
    result.selected = requested;
    if (requested == PlaybackCompositionMode::composite)
        return result;
    for (const SceneSource &source : document.sources) {
        if (source.kind != "rtsp" && source.kind != "camera")
            result.reasons.push_back(source.id + ": source kind requires Composite");
        if (!source.filters.empty())
            result.reasons.push_back(source.id + ": ordered filters require Composite");
    }
    for (const SceneItem &item : document.items) {
        if (item.rotation_degrees != 0.0 || item.opacity != 1.0 || item.blend_mode != "normal")
            result.reasons.push_back(item.id + ": advanced transform requires Composite");
    }
    if (!result.reasons.empty()) {
        result.exact = false;
        result.selected = requested == PlaybackCompositionMode::hybrid
                              ? PlaybackCompositionMode::hybrid
                              : PlaybackCompositionMode::composite;
    }
    return result;
}

SceneSerializeResult serialize_studio_capabilities_json(const StudioDocument &document, bool pretty)
{
    if (const auto error = validate_studio_document(document))
        return serialize_failure(*error);
    JsonPtr root(json_object());
    JsonPtr scenes(json_array());
    if (!root || !scenes || json_object_set_new(root.get(), "revision",
                                                json_integer(static_cast<json_int_t>(document.revision))) != 0)
        return serialize_failure("could not build Studio capability JSON");
    const auto mode_name = [](PlaybackCompositionMode mode) {
        return mode == PlaybackCompositionMode::direct ? "direct"
             : mode == PlaybackCompositionMode::hybrid ? "hybrid" : "composite";
    };
    for (const SceneDocument &scene : document.scenes) {
        JsonPtr object(json_object());
        if (!object || json_object_set_new(object.get(), "sceneId", json_string(scene.id.c_str())) != 0)
            return serialize_failure("could not build Studio capability scene");
        for (const auto [label, requested] : {
                 std::pair{"direct", PlaybackCompositionMode::direct},
                 std::pair{"hybrid", PlaybackCompositionMode::hybrid}}) {
            const SceneCapability capability = analyze_scene_capability(scene, requested);
            JsonPtr value(json_object());
            JsonPtr reasons(json_array());
            if (!value || !reasons ||
                json_object_set_new(value.get(), "selected", json_string(mode_name(capability.selected))) != 0 ||
                json_object_set_new(value.get(), "exact", json_boolean(capability.exact)) != 0)
                return serialize_failure("could not build Studio capability mode");
            for (const std::string &reason : capability.reasons) {
                if (json_array_append_new(reasons.get(), json_string(reason.c_str())) != 0)
                    return serialize_failure("could not build Studio capability reasons");
            }
            if (json_object_set_new(value.get(), "reasons", reasons.release()) != 0 ||
                json_object_set_new(object.get(), label, value.release()) != 0)
                return serialize_failure("could not build Studio capability mode");
        }
        if (json_array_append_new(scenes.get(), object.release()) != 0)
            return serialize_failure("could not build Studio capability scenes");
    }
    if (json_object_set_new(root.get(), "scenes", scenes.release()) != 0)
        return serialize_failure("could not build Studio capability JSON");
    char *encoded = json_dumps(root.get(), (pretty ? JSON_INDENT(2) : JSON_COMPACT) |
                                               JSON_SORT_KEYS | JSON_REAL_PRECISION(6));
    if (!encoded)
        return serialize_failure("could not encode Studio capability JSON");
    SceneSerializeResult result;
    result.json = encoded;
    std::free(encoded);
    return result;
}

StudioHistory::StudioHistory(std::size_t capacity) : capacity_(std::clamp<std::size_t>(capacity, 1, 1000)) {}

bool StudioHistory::push(std::string state)
{
    if (!undo_.empty() && undo_.back() == state)
        return false;
    undo_.push_back(std::move(state));
    if (undo_.size() > capacity_)
        undo_.erase(undo_.begin());
    redo_.clear();
    return true;
}

std::optional<std::string> StudioHistory::undo(std::string_view current)
{
    if (undo_.empty())
        return std::nullopt;
    redo_.emplace_back(current);
    std::string state = std::move(undo_.back());
    undo_.pop_back();
    return state;
}

std::optional<std::string> StudioHistory::redo(std::string_view current)
{
    if (redo_.empty())
        return std::nullopt;
    undo_.emplace_back(current);
    std::string state = std::move(redo_.back());
    redo_.pop_back();
    return state;
}

} // namespace webobs
