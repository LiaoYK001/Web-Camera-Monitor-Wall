#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs {

inline constexpr int current_scene_schema_version = 4;
inline constexpr std::size_t maximum_scene_json_bytes = 1024 * 1024;
inline constexpr std::size_t maximum_scene_sources = 64;
inline constexpr std::size_t maximum_browser_sources = 8;
inline constexpr std::size_t maximum_scene_items = 256;
inline constexpr std::size_t maximum_source_filters = 16;

struct SceneFilter {
    std::string id;
    std::string kind;
    bool enabled = true;
    double amount = 0.0;
    std::string value;

    bool operator==(const SceneFilter &) const = default;
};

struct SceneCanvas {
    int width = 1920;
    int height = 1080;
    std::string background_color = "#000000";

    bool operator==(const SceneCanvas &) const = default;
};

struct SceneSource {
    std::string id;
    std::string kind = "rtsp";
    std::string name;
    std::string rtsp_url;
    std::string transport = "tcp";
    std::string browser_url;
    int browser_width = 1280;
    int browser_height = 720;
    int browser_fps = 30;
    std::string browser_css;
    bool shutdown_when_hidden = true;
    bool restart_when_active = true;
    bool muted = true;
    double volume = 1.0;
    int sync_offset_ms = 0;
    std::string monitoring = "off";
    int audio_track = 1;
    std::string file_path;
    std::string text;
    std::string color = "#000000";
    std::string nested_scene_id;
    bool loop = true;
    std::vector<SceneFilter> filters;

    bool operator==(const SceneSource &) const = default;
};

struct SceneCrop {
    int top = 0;
    int right = 0;
    int bottom = 0;
    int left = 0;

    bool operator==(const SceneCrop &) const = default;
};

struct SceneItem {
    std::string id;
    std::string source_id;
    int x = 0;
    int y = 0;
    int width = 640;
    int height = 360;
    std::string scale_mode = "contain";
    SceneCrop crop;
    int z_index = 0;
    bool visible = true;
    bool locked = false;
    std::string group_id;
    double rotation_degrees = 0.0;
    double opacity = 1.0;
    std::string blend_mode = "normal";

    bool operator==(const SceneItem &) const = default;
};

struct SceneDocument {
    int schema_version = current_scene_schema_version;
    std::uint64_t revision = 0;
    std::string id = "main";
    std::string name = "Main";
    SceneCanvas canvas;
    std::vector<SceneSource> sources;
    std::vector<SceneItem> items;

    bool operator==(const SceneDocument &) const = default;
};

enum class SceneJsonView {
    persistence,
    public_api,
};

struct SceneParseResult {
    std::optional<SceneDocument> document;
    std::string error;

    [[nodiscard]] bool ok() const { return document.has_value() && error.empty(); }
};

struct SceneSerializeResult {
    std::string json;
    std::string error;

    [[nodiscard]] bool ok() const { return !json.empty() && error.empty(); }
};

std::optional<std::string> validate_scene_document(const SceneDocument &document);
SceneParseResult parse_scene_json(std::string_view json);
SceneSerializeResult serialize_scene_json(const SceneDocument &document, SceneJsonView view,
                                          bool pretty = false);

} // namespace webobs
