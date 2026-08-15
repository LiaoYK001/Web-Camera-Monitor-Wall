#pragma once

#include "webobs/scene_document.hpp"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs {

inline constexpr int current_studio_schema_version = 1;
inline constexpr std::size_t maximum_studio_scenes = 64;
inline constexpr std::size_t maximum_undo_entries = 100;

struct StudioTransition {
    std::string kind = "cut";
    int duration_ms = 300;

    bool operator==(const StudioTransition &) const = default;
};

struct StudioDocument {
    int schema_version = current_studio_schema_version;
    std::uint64_t revision = 0;
    std::string program_scene_id = "main";
    std::string preview_scene_id = "main";
    StudioTransition transition;
    std::vector<SceneDocument> scenes;

    bool operator==(const StudioDocument &) const = default;
};

struct StudioParseResult {
    std::optional<StudioDocument> document;
    std::string error;

    [[nodiscard]] bool ok() const { return document.has_value() && error.empty(); }
};

struct StudioFlattenResult {
    std::optional<SceneDocument> document;
    std::string error;

    [[nodiscard]] bool ok() const { return document.has_value() && error.empty(); }
};

enum class PlaybackCompositionMode {
    composite,
    direct,
    hybrid,
};

struct SceneCapability {
    PlaybackCompositionMode requested = PlaybackCompositionMode::composite;
    PlaybackCompositionMode selected = PlaybackCompositionMode::composite;
    bool exact = true;
    std::vector<std::string> reasons;
};

std::optional<std::string> validate_studio_document(const StudioDocument &document);
StudioParseResult parse_studio_json(std::string_view json);
SceneSerializeResult serialize_studio_json(const StudioDocument &document, SceneJsonView view,
                                           bool pretty = false);
StudioFlattenResult flatten_studio_scene(const StudioDocument &document, std::string_view scene_id);
SceneCapability analyze_scene_capability(const SceneDocument &document,
                                         PlaybackCompositionMode requested);
SceneSerializeResult serialize_studio_capabilities_json(const StudioDocument &document,
                                                         bool pretty = false);

// Bounded, byte-exact history used by both the REST controller and the browser editor.
class StudioHistory {
public:
    explicit StudioHistory(std::size_t capacity = maximum_undo_entries);

    bool push(std::string state);
    std::optional<std::string> undo(std::string_view current);
    std::optional<std::string> redo(std::string_view current);
    [[nodiscard]] std::size_t undo_size() const { return undo_.size(); }
    [[nodiscard]] std::size_t redo_size() const { return redo_.size(); }

private:
    std::size_t capacity_;
    std::vector<std::string> undo_;
    std::vector<std::string> redo_;
};

} // namespace webobs
