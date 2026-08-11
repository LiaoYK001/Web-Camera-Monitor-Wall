#include "webobs/config.hpp"
#include "webobs/redaction.hpp"
#include "webobs/scene_document.hpp"

#include <cstdint>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

int failures = 0;

void expect(bool condition, std::string_view message)
{
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

webobs::EnvironmentLookup environment(std::map<std::string, std::string> values)
{
    return [values = std::move(values)](std::string_view name) -> std::optional<std::string> {
        const auto iterator = values.find(std::string(name));
        if (iterator == values.end())
            return std::nullopt;
        return iterator->second;
    };
}

void config_tests()
{
    const auto empty_environment = environment({});
    auto result = webobs::parse_config({}, empty_environment);
    expect(!result.ok(), "missing RTSP URL must fail");

    const std::vector<std::pair<std::string, std::string>> invalid_values = {
        {"--duration-seconds", "-1"},       {"--height", "0"},
        {"--fps", "121"},                  {"--bitrate-kbps", "49"},
        {"--connect-timeout-seconds", "0"}, {"--log-level", "verbose"},
    };
    for (const auto &[flag, value] : invalid_values) {
        result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", flag, value}, empty_environment);
        expect(!result.ok(), flag + " must reject an out-of-range value");
    }

    result = webobs::parse_config({"--rtsp-url", "http://camera/live"}, empty_environment);
    expect(!result.ok(), "non-RTSP URL must fail");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--width", "1919"}, empty_environment);
    expect(!result.ok(), "odd NV12 width must fail");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--rtsp-transport", "quic"}, empty_environment);
    expect(!result.ok(), "unsupported RTSP transport must fail");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--output", "capture.mkv"}, empty_environment);
    expect(!result.ok(), "non-MP4 output must fail");

    result = webobs::parse_config(
        {"--rtsp-url", "rtsp://cli/live", "--fps", "25"},
        environment({{"WEBOBS_RTSP_URL", "rtsp://environment/live"}, {"WEBOBS_FPS", "15"}}));
    expect(result.ok() && result.config.has_value(), "valid CLI configuration must parse");
    if (result.config) {
        expect(result.config->rtsp_url == "rtsp://cli/live", "CLI URL must override environment URL");
        expect(result.config->fps == 25, "CLI FPS must override environment FPS");
        expect(result.config->output_path.ends_with(".mp4"), "default output must be MP4");
    }

    result = webobs::parse_config({"--help"}, environment({{"WEBOBS_WIDTH", "broken"}}));
    expect(result.ok() && result.action == webobs::ParseAction::show_help, "help must not require valid runtime settings");

    result = webobs::parse_config({"--version"}, environment({{"WEBOBS_FPS", "broken"}}));
    expect(result.ok() && result.action == webobs::ParseAction::show_version,
           "version must not require valid runtime settings");

    result = webobs::parse_config({}, environment({{"WEBOBS_RTSP_URL", "rtsp://environment/live"},
                                                    {"WEBOBS_RTSP_TRANSPORT", "UDP"},
                                                    {"WEBOBS_LOG_LEVEL", "WARN"}}));
    expect(result.ok() && result.config.has_value(), "valid environment-only configuration must parse");
    if (result.config) {
        expect(result.config->rtsp_transport == "udp", "transport must be normalized to lowercase");
        expect(result.config->log_level == webobs::LogLevel::warning, "log level must be normalized");
        expect(result.config->output_path.starts_with("/recordings/webobs-"),
               "default output must be generated under /recordings");
    }
}

void redaction_tests()
{
    expect(webobs::redact_rtsp_credentials("rtsp://camera/live") == "rtsp://camera/live",
           "credential-free RTSP URL must not change");
    expect(webobs::redact_rtsp_credentials("rtsp://user:password@camera/live") == "rtsp://***:***@camera/live",
           "username and password must be redacted");
    expect(webobs::redact_rtsp_credentials("rtsps://user@camera/live") == "rtsps://***@camera/live",
           "username-only RTSPS URL must be redacted");
    expect(webobs::redact_rtsp_credentials("rtsp://name:p%40ss@[2001:db8::1]:554/live") ==
               "rtsp://***:***@[2001:db8::1]:554/live",
           "encoded credentials and IPv6 hosts must be handled");
    expect(webobs::redact_rtsp_credentials("a rtsp://u:p@one/live b rtsp://x:y@two/live") ==
               "a rtsp://***:***@one/live b rtsp://***:***@two/live",
           "all credentials in one log line must be redacted");
}

webobs::SceneDocument valid_scene_document()
{
    webobs::SceneDocument document;
    document.revision = 7;
    document.id = "main";
    document.name = "Main Wall";
    document.canvas = {.width = 1920, .height = 1080, .background_color = "#000000"};
    document.sources.push_back({.id = "camera-front",
                                .name = "Front Camera",
                                .rtsp_url = "rtsp://user:password@camera/live",
                                .transport = "tcp",
                                .muted = false,
                                .volume = 0.75});
    document.items.push_back({.id = "item-front",
                              .source_id = "camera-front",
                              .x = 100,
                              .y = 50,
                              .width = 960,
                              .height = 540,
                              .crop = {.top = 1, .right = 2, .bottom = 3, .left = 4},
                              .z_index = 0,
                              .visible = true});
    return document;
}

void scene_document_tests()
{
    webobs::SceneDocument document = valid_scene_document();
    expect(!webobs::validate_scene_document(document).has_value(), "valid scene document must pass validation");

    const auto persistent =
        webobs::serialize_scene_json(document, webobs::SceneJsonView::persistence, true);
    expect(persistent.ok(), "valid scene document must serialize for persistence");
    expect(persistent.json.find("user:password") != std::string::npos,
           "persistence view must retain the RTSP secret required by the engine");

    const auto public_view =
        webobs::serialize_scene_json(document, webobs::SceneJsonView::public_api, false);
    expect(public_view.ok(), "valid scene document must serialize for the public API");
    expect(public_view.json.find("user:password") == std::string::npos,
           "public scene JSON must not expose RTSP credentials");
    expect(public_view.json.find("rtsp://***:***@camera/live") != std::string::npos,
           "public scene JSON must retain a recognizable redacted endpoint");

    const auto parsed = webobs::parse_scene_json(persistent.json);
    expect(parsed.ok(), "serialized persistence JSON must parse");
    if (parsed.document)
        expect(*parsed.document == document, "scene persistence JSON must round-trip without data loss");

    const auto compact = webobs::serialize_scene_json(document, webobs::SceneJsonView::persistence, false);
    const auto compact_again = webobs::serialize_scene_json(document, webobs::SceneJsonView::persistence, false);
    expect(compact.ok() && compact_again.ok() && compact.json == compact_again.json,
           "scene JSON serialization must be deterministic");

    auto invalid = document;
    invalid.sources.push_back(invalid.sources.front());
    expect(webobs::validate_scene_document(invalid).has_value(), "duplicate source ids must fail validation");

    invalid = document;
    invalid.items.front().source_id = "missing-source";
    expect(webobs::validate_scene_document(invalid).has_value(), "dangling item source references must fail");

    invalid = document;
    invalid.items.front().z_index = 1;
    expect(webobs::validate_scene_document(invalid).has_value(), "non-contiguous item z-index values must fail");

    invalid = document;
    invalid.canvas.width = 1919;
    expect(webobs::validate_scene_document(invalid).has_value(), "odd canvas width must fail validation");

    invalid = document;
    invalid.sources.front().volume = 1.01;
    expect(webobs::validate_scene_document(invalid).has_value(), "source volume above one must fail validation");

    invalid = document;
    invalid.sources.front().rtsp_url = "rtsp://user:password@";
    expect(webobs::validate_scene_document(invalid).has_value(), "RTSP URL without a host must fail validation");

    invalid = document;
    invalid.revision = std::numeric_limits<std::uint64_t>::max();
    expect(webobs::validate_scene_document(invalid).has_value(), "revision outside signed JSON range must fail");

    std::string unsupported_field = compact.json;
    unsupported_field.insert(1, "\"unexpected\":true,");
    expect(!webobs::parse_scene_json(unsupported_field).ok(), "unknown scene fields must be rejected");

    std::string future_schema = compact.json;
    const std::string schema_one = "\"schemaVersion\":1";
    const std::size_t schema_position = future_schema.find(schema_one);
    if (schema_position != std::string::npos)
        future_schema.replace(schema_position, schema_one.size(), "\"schemaVersion\":2");
    expect(schema_position != std::string::npos && !webobs::parse_scene_json(future_schema).ok(),
           "future scene schema versions must be rejected");

    const std::string duplicate_key =
        R"({"schemaVersion":1,"schemaVersion":1,"revision":0,"id":"main","name":"Main","canvas":{"width":1920,"height":1080,"backgroundColor":"#000000"},"sources":[],"items":[]})";
    expect(!webobs::parse_scene_json(duplicate_key).ok(), "duplicate JSON keys must be rejected");

    const std::string secret_in_invalid_json = R"({"name":"sensitive-value")";
    const auto invalid_json = webobs::parse_scene_json(secret_in_invalid_json);
    expect(!invalid_json.ok() && invalid_json.error.find("sensitive-value") == std::string::npos,
           "JSON parse errors must not echo potentially sensitive input");

    const std::string oversized(webobs::maximum_scene_json_bytes + 1, 'x');
    expect(!webobs::parse_scene_json(oversized).ok(), "oversized scene JSON must be rejected before parsing");
}

} // namespace

int main()
{
    config_tests();
    redaction_tests();
    scene_document_tests();
    if (failures == 0) {
        std::cout << "All webobs unit tests passed\n";
        return 0;
    }
    std::cerr << failures << " test(s) failed\n";
    return 1;
}
