#include "webobs/config.hpp"
#include "webobs/browser_security.hpp"
#include "webobs/redaction.hpp"
#include "webobs/scene_document.hpp"
#include "webobs/scene_mutation.hpp"
#include "webobs/scene_store.hpp"

#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <sys/stat.h>
#include <unistd.h>

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
        {"--http-port", "65536"},          {"--allow-insecure-remote", "sometimes"},
        {"--webrtc-enabled", "sometimes"},
        {"--browser-allow-private-networks", "sometimes"},
    };
    for (const auto &[flag, value] : invalid_values) {
        result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", flag, value}, empty_environment);
        expect(!result.ok(), flag + " must reject an out-of-range value");
    }

    result = webobs::parse_config({"--rtsp-url", "http://camera/live"}, empty_environment);
    expect(!result.ok(), "non-RTSP URL must fail");

    result = webobs::parse_config({"--scene-file", "relative.json"}, empty_environment);
    expect(!result.ok(), "relative scene file path must fail");

    result = webobs::parse_config({"--scene-file", "/config/webobs/scene.txt"}, empty_environment);
    expect(!result.ok(), "non-JSON scene file path must fail");

    result = webobs::parse_config({"--scene-file", "/config/webobs/scene.json"}, empty_environment);
    expect(result.ok() && result.config && result.config->rtsp_url.empty(),
           "absolute scene file must allow startup without a bootstrap URL");

    result = webobs::parse_config(
        {"--scene-file", "/config/webobs/cli.json"},
        environment({{"WEBOBS_SCENE_FILE", "/config/webobs/environment.json"}}));
    expect(result.ok() && result.config && result.config->scene_file == "/config/webobs/cli.json",
           "CLI scene file must override the environment scene file");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--width", "1919"}, empty_environment);
    expect(!result.ok(), "odd NV12 width must fail");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--rtsp-transport", "quic"}, empty_environment);
    expect(!result.ok(), "unsupported RTSP transport must fail");

    result = webobs::parse_config(
        {"--rtsp-url", "rtsp://camera/live", "--listen-address", "0.0.0.0"}, empty_environment);
    expect(!result.ok(), "non-loopback listener must require an explicit insecure-remote opt-in");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--listen-address", "0.0.0.0",
                                   "--allow-insecure-remote", "true"},
                                  empty_environment);
    expect(result.ok() && result.config && result.config->allow_insecure_remote,
           "explicit insecure-remote opt-in must allow a container listener");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--output", "capture.mkv"}, empty_environment);
    expect(!result.ok(), "non-MP4 output must fail");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--webrtc-enabled", "true",
                                   "--whip-url", "http://name:secret@router/program/whip"},
                                  empty_environment);
    expect(!result.ok(), "WHIP URLs containing credentials must fail");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--webrtc-enabled", "true",
                                   "--whip-url", "https://router/program/whip?token=secret"},
                                  empty_environment);
    expect(!result.ok(), "WHIP URLs containing query credentials must fail");

    result = webobs::parse_config({"--rtsp-url", "rtsp://camera/live", "--webrtc-enabled", "true",
                                   "--whip-url", "http://127.0.0.1:8889/program/whip"},
                                  empty_environment);
    expect(result.ok() && result.config && result.config->webrtc_enabled,
           "valid WHIP configuration must enable WebRTC publishing");

    result = webobs::parse_config(
        {"--rtsp-url", "rtsp://camera/live", "--webrtc-enabled", "false"},
        environment({{"WEBOBS_WEBRTC_ENABLED", "true"}, {"WEBOBS_WHIP_URL", "not-a-url"}}));
    expect(result.ok() && result.config && !result.config->webrtc_enabled,
           "CLI WebRTC setting must override the environment and ignore a disabled WHIP URL");

    result = webobs::parse_config(
        {"--scene-file", "/config/webobs/scene.json", "--browser-allowed-origins",
         "HTTPS://Dashboard.Example:443/, http://overlay.example:8080"},
        empty_environment);
    expect(result.ok() && result.config && result.config->browser_security.allowed_origins.size() == 2 &&
               result.config->browser_security.allowed_origins.front() == "https://dashboard.example",
           "browser origin allowlist must be normalized and bounded");

    result = webobs::parse_config(
        {"--scene-file", "/config/webobs/scene.json", "--browser-allowed-origins",
         "https://name:secret@dashboard.example"},
        empty_environment);
    expect(!result.ok(), "browser allowed origins containing credentials must fail");

    result = webobs::parse_config(
        {"--scene-file", "/config/webobs/scene.json", "--browser-allowed-origins",
         "https://dashboard.example/path"},
        empty_environment);
    expect(!result.ok(), "browser allowed origins containing paths must fail");

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
    expect(webobs::redact_browser_url("https://dashboard.example/view?token=secret#panel") ==
               "https://dashboard.example/view?***#***",
           "browser URL query and fragment values must be redacted");
    expect(webobs::redact_url_secrets(
               "open https://name:secret@dashboard.example/view?token=secret then rtsp://u:p@camera/live") ==
               "open https://***@dashboard.example/view?*** then rtsp://***:***@camera/live",
           "combined log redaction must cover browser and RTSP secrets");
}

void browser_security_tests()
{
    const auto public_url = webobs::parse_browser_url("https://Dashboard.Example:443/view?token=value");
    expect(public_url.ok() && public_url.parts->origin == "https://dashboard.example",
           "browser URL parser must normalize origins without exposing the path");
    expect(!webobs::parse_browser_url("file:///etc/passwd").ok(),
           "browser URL parser must reject file URLs");
    expect(!webobs::parse_browser_url("http://name:secret@example.invalid/").ok(),
           "browser URL parser must reject URL userinfo");

    webobs::BrowserSecurityPolicy policy{.allowed_origins = {"https://dashboard.example"}};
    expect(!webobs::validate_browser_url_policy("https://dashboard.example/view", policy).has_value(),
           "an exact public origin on the allowlist must pass policy validation");
    expect(webobs::validate_browser_url_policy("https://other.example/view", policy).has_value(),
           "an origin outside the allowlist must fail policy validation");
    policy.allowed_origins = {"http://127.0.0.1"};
    expect(webobs::validate_browser_url_policy("http://127.0.0.1/view", policy).has_value(),
           "private browser destinations must require a second explicit opt-in");
    policy.allow_private_networks = true;
    expect(!webobs::validate_browser_url_policy("http://127.0.0.1/view", policy).has_value(),
           "allowlisted private browser destinations must pass only with explicit opt-in");
}

webobs::SceneDocument valid_scene_document()
{
    webobs::SceneDocument document;
    document.revision = 7;
    document.id = "main";
    document.name = "Main Wall";
    document.canvas = {.width = 1920, .height = 1080, .background_color = "#000000"};
    webobs::SceneSource source;
    source.id = "camera-front";
    source.name = "Front Camera";
    source.rtsp_url = "rtsp://user:password@camera/live";
    source.transport = "tcp";
    source.muted = false;
    source.volume = 0.75;
    document.sources.push_back(std::move(source));
    document.items.push_back({.id = "item-front",
                              .source_id = "camera-front",
                              .x = 100,
                              .y = 50,
                              .width = 960,
                              .height = 540,
                              .scale_mode = "contain",
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

    webobs::SceneDocument browser_document;
    browser_document.sources.push_back({.id = "dashboard-main",
                                        .kind = "browser",
                                        .name = "Operations Dashboard",
                                        .rtsp_url = {},
                                        .transport = {},
                                        .browser_url = "https://dashboard.example/view?token=sensitive#wall",
                                        .browser_width = 1280,
                                        .browser_height = 720,
                                        .browser_fps = 30,
                                        .browser_css = "body { overflow: hidden; }",
                                        .shutdown_when_hidden = true,
                                        .restart_when_active = true,
                                        .muted = true,
                                        .volume = 1.0});
    webobs::SceneItem browser_item;
    browser_item.id = "item-dashboard-main";
    browser_item.source_id = "dashboard-main";
    browser_item.width = 1920;
    browser_item.height = 1080;
    browser_document.items.push_back(std::move(browser_item));
    expect(!webobs::validate_scene_document(browser_document).has_value(),
           "valid browser source document must pass structural validation");
    const auto browser_persistent =
        webobs::serialize_scene_json(browser_document, webobs::SceneJsonView::persistence, false);
    const auto browser_public =
        webobs::serialize_scene_json(browser_document, webobs::SceneJsonView::public_api, false);
    expect(browser_persistent.ok() && webobs::parse_scene_json(browser_persistent.json).ok(),
           "browser source settings must persist and parse in schema v2");
    expect(browser_public.ok() && browser_public.json.find("token=sensitive") == std::string::npos &&
               browser_public.json.find("?***#***") != std::string::npos,
           "public browser source JSON must redact query and fragment secrets");

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
    invalid.canvas.background_color = "#ffffff";
    expect(webobs::validate_scene_document(invalid).has_value(), "non-black M1 canvas background must fail validation");

    invalid = document;
    invalid.items.front().scale_mode = "tile";
    expect(webobs::validate_scene_document(invalid).has_value(), "unsupported item scale mode must fail validation");

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
    const std::string schema_two = "\"schemaVersion\":2";
    const std::size_t schema_position = future_schema.find(schema_two);
    if (schema_position != std::string::npos)
        future_schema.replace(schema_position, schema_two.size(), "\"schemaVersion\":3");
    expect(schema_position != std::string::npos && !webobs::parse_scene_json(future_schema).ok(),
           "future scene schema versions must be rejected");

    const std::string duplicate_key =
        R"({"schemaVersion":2,"schemaVersion":2,"revision":0,"id":"main","name":"Main","canvas":{"width":1920,"height":1080,"backgroundColor":"#000000"},"sources":[],"items":[]})";
    expect(!webobs::parse_scene_json(duplicate_key).ok(), "duplicate JSON keys must be rejected");

    const std::string secret_in_invalid_json = R"({"name":"sensitive-value")";
    const auto invalid_json = webobs::parse_scene_json(secret_in_invalid_json);
    expect(!invalid_json.ok() && invalid_json.error.find("sensitive-value") == std::string::npos,
           "JSON parse errors must not echo potentially sensitive input");

    const std::string oversized(webobs::maximum_scene_json_bytes + 1, 'x');
    expect(!webobs::parse_scene_json(oversized).ok(), "oversized scene JSON must be rejected before parsing");
}

std::string read_test_file(const std::filesystem::path &path)
{
    std::ifstream stream(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}

bool write_test_file(const std::filesystem::path &path, std::string_view content, mode_t mode)
{
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream.write(content.data(), static_cast<std::streamsize>(content.size()));
    stream.close();
    return stream.good() && chmod(path.c_str(), mode) == 0;
}

mode_t file_mode(const std::filesystem::path &path)
{
    struct stat metadata {};
    if (stat(path.c_str(), &metadata) != 0)
        return std::numeric_limits<mode_t>::max();
    return metadata.st_mode & 0777;
}

void scene_store_tests()
{
    char directory_template[] = "/tmp/webobs-scene-store-XXXXXX";
    const char *created_directory = mkdtemp(directory_template);
    expect(created_directory != nullptr, "scene store test directory must be created");
    if (!created_directory)
        return;

    const std::filesystem::path root(created_directory);
    struct Cleanup {
        std::filesystem::path path;
        ~Cleanup()
        {
            std::error_code error;
            std::filesystem::remove_all(path, error);
        }
    } cleanup{root};

    const std::filesystem::path scene_path = root / "private" / "scene.json";
    const webobs::SceneDocument document = valid_scene_document();
    const auto save_error = webobs::save_scene_file_atomic(scene_path, document);
    expect(!save_error.has_value(), "valid scene must be saved atomically");
    if (save_error)
        return;

    expect(file_mode(scene_path.parent_path()) == 0700, "scene storage directory must use mode 0700");
    expect(file_mode(scene_path) == 0600, "scene file must use mode 0600");
    const auto loaded = webobs::load_scene_file(scene_path);
    expect(loaded.ok() && loaded.status == webobs::SceneFileStatus::loaded && loaded.document == document,
           "current scene file must load without migration");

    bool temporary_file_found = false;
    for (const auto &entry : std::filesystem::directory_iterator(scene_path.parent_path())) {
        if (entry.path().filename().string().find(".tmp.") != std::string::npos)
            temporary_file_found = true;
    }
    expect(!temporary_file_found, "successful atomic save must not leave a temporary file");

    const std::string original_content = read_test_file(scene_path);
    auto invalid_document = document;
    invalid_document.canvas.width = 1919;
    expect(webobs::save_scene_file_atomic(scene_path, invalid_document).has_value(),
           "invalid scene must not be saved");
    expect(read_test_file(scene_path) == original_content,
           "failed validation must leave the existing scene file unchanged");

    const auto compact = webobs::serialize_scene_json(document, webobs::SceneJsonView::persistence, false);
    expect(compact.ok(), "migration fixture must serialize");
    if (!compact.ok())
        return;
    std::string legacy_json = compact.json;
    const std::string current_version = "\"schemaVersion\":2";
    const std::size_t version_position = legacy_json.find(current_version);
    const std::string revision = "\"revision\":7,";
    const std::size_t revision_position = legacy_json.find(revision);
    expect(version_position != std::string::npos && revision_position != std::string::npos,
           "migration fixture must contain version and revision fields");
    if (version_position == std::string::npos || revision_position == std::string::npos)
        return;

    std::string version_one_json = compact.json;
    version_one_json.replace(version_position, current_version.size(), "\"schemaVersion\":1");
    const auto version_one_migration = webobs::migrate_scene_json(version_one_json);
    expect(version_one_migration.ok() && version_one_migration.migrated &&
               version_one_migration.document->schema_version == 2 &&
               version_one_migration.document->revision == document.revision,
           "schemaVersion 1 must migrate to schemaVersion 2 without changing revision");

    legacy_json.replace(version_position, current_version.size(), "\"schemaVersion\":0");
    legacy_json.erase(revision_position, revision.size());

    const auto migrated_in_memory = webobs::migrate_scene_json(legacy_json);
    expect(migrated_in_memory.ok() && migrated_in_memory.migrated && migrated_in_memory.document->revision == 0,
           "schemaVersion 0 must migrate to revision zero");

    const std::filesystem::path legacy_path = scene_path.parent_path() / "legacy.json";
    expect(write_test_file(legacy_path, legacy_json, 0644), "legacy scene fixture must be written");
    const auto migrated_file = webobs::load_scene_file(legacy_path);
    expect(migrated_file.ok() && migrated_file.status == webobs::SceneFileStatus::migrated &&
               migrated_file.document && migrated_file.document->schema_version == 2 &&
               migrated_file.document->revision == 0,
           "legacy scene file must migrate and load");
    expect(file_mode(legacy_path) == 0600, "loaded legacy scene permissions must be tightened to 0600");
    const auto rewritten = webobs::parse_scene_json(read_test_file(legacy_path));
    expect(rewritten.ok() && rewritten.document && rewritten.document->revision == 0,
           "migrated scene must be atomically rewritten as current JSON");

    std::string future_json = compact.json;
    future_json.replace(future_json.find(current_version), current_version.size(), "\"schemaVersion\":3");
    const std::filesystem::path future_path = scene_path.parent_path() / "future.json";
    expect(write_test_file(future_path, future_json, 0600), "future scene fixture must be written");
    const auto future = webobs::load_scene_file(future_path);
    expect(!future.ok(), "future scene schema must be rejected");
    expect(read_test_file(future_path) == future_json, "rejected future scene must not be rewritten");

    const std::filesystem::path malformed_path = scene_path.parent_path() / "malformed.json";
    const std::string malformed = R"({"schemaVersion":2,"name":"sensitive-value")";
    expect(write_test_file(malformed_path, malformed, 0600), "malformed scene fixture must be written");
    const auto malformed_result = webobs::load_scene_file(malformed_path);
    expect(!malformed_result.ok() && malformed_result.error.find("sensitive-value") == std::string::npos,
           "scene store errors must not echo secret-bearing file content");

    const std::filesystem::path missing_path = scene_path.parent_path() / "missing.json";
    const auto missing = webobs::load_scene_file(missing_path);
    expect(missing.ok() && missing.status == webobs::SceneFileStatus::not_found && !missing.document,
           "missing scene file must be reported without an error");

    const std::filesystem::path victim_path = scene_path.parent_path() / "victim.txt";
    const std::string victim_content = "must remain unchanged";
    expect(write_test_file(victim_path, victim_content, 0600), "symlink victim fixture must be written");
    const std::filesystem::path symlink_path = scene_path.parent_path() / "symlink.json";
    expect(symlink(victim_path.c_str(), symlink_path.c_str()) == 0, "scene symlink fixture must be created");
    expect(webobs::save_scene_file_atomic(symlink_path, document).has_value(),
           "atomic save must reject a symbolic-link target");
    expect(read_test_file(victim_path) == victim_content, "rejected symlink save must not alter its target");

    const std::filesystem::path hardlink_path = scene_path.parent_path() / "hardlink.json";
    expect(link(victim_path.c_str(), hardlink_path.c_str()) == 0, "scene hard-link fixture must be created");
    expect(webobs::save_scene_file_atomic(hardlink_path, document).has_value(),
           "atomic save must reject a target with additional hard links");
    expect(read_test_file(victim_path) == victim_content, "rejected hard-link save must not alter its target");

    expect(webobs::save_scene_file_atomic("relative-scene.json", document).has_value(),
           "scene save must reject a relative path");
    expect(!webobs::load_scene_file("relative-scene.json").ok(), "scene load must reject a relative path");
}

void scene_mutation_tests()
{
    const webobs::SceneDocument current = valid_scene_document();
    const auto public_json =
        webobs::serialize_scene_json(current, webobs::SceneJsonView::public_api, false);
    expect(public_json.ok(), "scene mutation fixture must serialize as a public document");
    if (!public_json.ok())
        return;

    auto candidate = webobs::parse_scene_json(public_json.json);
    expect(candidate.ok(), "redacted public scene must remain structurally parseable");
    if (!candidate.ok())
        return;
    candidate.document->items.front().x = 321;
    const auto moved_json =
        webobs::serialize_scene_json(*candidate.document, webobs::SceneJsonView::persistence, false);
    const auto moved = webobs::plan_scene_replacement(current, moved_json.json, current.revision);
    expect(moved.ok() && moved.document->revision == current.revision + 1 &&
               moved.document->items.front().x == 321,
           "matching If-Match must plan one revision-advancing scene change");
    expect(moved.ok() && moved.document->sources.front().rtsp_url == current.sources.front().rtsp_url,
           "unchanged redacted source URL must restore its persisted credentials");

    const auto missing_precondition = webobs::plan_scene_replacement(current, moved_json.json, std::nullopt);
    expect(missing_precondition.rejection == webobs::SceneMutationRejection::precondition_required,
           "scene mutation must require If-Match");

    const auto stale = webobs::plan_scene_replacement(current, moved_json.json, current.revision - 1);
    expect(stale.rejection == webobs::SceneMutationRejection::revision_conflict,
           "stale If-Match must reject a scene mutation");

    candidate.document->revision = current.revision - 1;
    const auto wrong_body_revision =
        webobs::serialize_scene_json(*candidate.document, webobs::SceneJsonView::persistence, false);
    const auto body_conflict =
        webobs::plan_scene_replacement(current, wrong_body_revision.json, current.revision);
    expect(body_conflict.rejection == webobs::SceneMutationRejection::revision_conflict,
           "body revision must match If-Match");

    candidate.document->revision = current.revision;
    candidate.document->sources.front().id = "new-source";
    candidate.document->items.front().source_id = "new-source";
    const auto masked_new_json =
        webobs::serialize_scene_json(*candidate.document, webobs::SceneJsonView::persistence, false);
    const auto masked_new = webobs::plan_scene_replacement(current, masked_new_json.json, current.revision);
    expect(masked_new.rejection == webobs::SceneMutationRejection::invalid_document,
           "new source must not accept credential placeholders");

    candidate = webobs::parse_scene_json(public_json.json);
    candidate.document->sources.front().rtsp_url = "rtsp://***:***@different.invalid/live";
    const auto masked_changed_json =
        webobs::serialize_scene_json(*candidate.document, webobs::SceneJsonView::persistence, false);
    const auto masked_changed =
        webobs::plan_scene_replacement(current, masked_changed_json.json, current.revision);
    expect(masked_changed.rejection == webobs::SceneMutationRejection::invalid_document,
           "changed endpoint must not accept credential placeholders");

    candidate.document->sources.front().rtsp_url = "rtsp://u:p@different.invalid/live";
    const auto replacement_json =
        webobs::serialize_scene_json(*candidate.document, webobs::SceneJsonView::persistence, false);
    const auto replacement =
        webobs::plan_scene_replacement(current, replacement_json.json, current.revision);
    expect(replacement.ok() && replacement.document->sources.front().rtsp_url.find("u:p") != std::string::npos,
           "explicit replacement credentials must be accepted for a changed endpoint");

    webobs::SceneDocument browser_current = valid_scene_document();
    browser_current.sources.front().kind = "browser";
    browser_current.sources.front().rtsp_url.clear();
    browser_current.sources.front().transport.clear();
    browser_current.sources.front().browser_url =
        "https://dashboard.example/view?token=persisted#panel";
    const auto browser_public =
        webobs::serialize_scene_json(browser_current, webobs::SceneJsonView::public_api, false);
    auto browser_candidate = webobs::parse_scene_json(browser_public.json);
    browser_candidate.document->items.front().x = 456;
    const auto browser_candidate_json = webobs::serialize_scene_json(
        *browser_candidate.document, webobs::SceneJsonView::persistence, false);
    const auto browser_moved = webobs::plan_scene_replacement(
        browser_current, browser_candidate_json.json, browser_current.revision);
    expect(browser_moved.ok() &&
               browser_moved.document->sources.front().browser_url ==
                   browser_current.sources.front().browser_url,
           "unchanged redacted browser URL must restore its persisted query and fragment");

    browser_candidate.document->sources.front().id = "new-browser";
    browser_candidate.document->items.front().source_id = "new-browser";
    const auto masked_browser_json = webobs::serialize_scene_json(
        *browser_candidate.document, webobs::SceneJsonView::persistence, false);
    const auto masked_browser = webobs::plan_scene_replacement(
        browser_current, masked_browser_json.json, browser_current.revision);
    expect(masked_browser.rejection == webobs::SceneMutationRejection::invalid_document,
           "new browser source must not accept query or fragment placeholders");

    const auto secret_error = webobs::plan_scene_replacement(
        current, R"({"schemaVersion":2,"name":"do-not-echo-this-secret")", current.revision);
    expect(!secret_error.ok() && secret_error.error.find("do-not-echo-this-secret") == std::string::npos,
           "scene mutation errors must not echo secret-bearing input");
}

} // namespace

int main()
{
    config_tests();
    redaction_tests();
    browser_security_tests();
    scene_document_tests();
    scene_store_tests();
    scene_mutation_tests();
    if (failures == 0) {
        std::cout << "All webobs unit tests passed\n";
        return 0;
    }
    std::cerr << failures << " test(s) failed\n";
    return 1;
}
