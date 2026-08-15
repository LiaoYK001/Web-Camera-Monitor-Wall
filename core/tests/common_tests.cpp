#include "webobs/config.hpp"
#include "webobs/authentication.hpp"
#include "webobs/audit_event.hpp"
#include "webobs/browser_security.hpp"
#include "webobs/redaction.hpp"
#include "webobs/scene_document.hpp"
#include "webobs/scene_mutation.hpp"
#include "webobs/scene_store.hpp"
#include "webobs/studio_document.hpp"
#include "webobs/studio_store.hpp"
#include "webobs/video_encoder.hpp"

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
        {"--video-encoder", "gpu-magic"},
        {"--vaapi-device", "/tmp/renderD128"},
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

    result = webobs::parse_config(
        {"--scene-file", "/config/webobs/scene.json", "--source-stale-seconds", "4",
         "--source-recovery-base-seconds", "2", "--source-recovery-max-seconds", "8"},
        empty_environment);
    expect(result.ok() && result.config && result.config->source_stale_seconds == 4 &&
               result.config->source_recovery_base_seconds == 2 &&
               result.config->source_recovery_max_seconds == 8,
           "source health and recovery settings must parse within bounds");
    result = webobs::parse_config(
        {"--scene-file", "/config/webobs/scene.json", "--source-recovery-base-seconds", "10",
         "--source-recovery-max-seconds", "5"},
        empty_environment);
    expect(!result.ok(), "source recovery maximum must not be below its base backoff");

    char auth_directory_template[] = "/tmp/webobs-auth-config-XXXXXX";
    const char *auth_directory = mkdtemp(auth_directory_template);
    expect(auth_directory != nullptr, "authentication config test directory must be created");
    if (auth_directory) {
        const std::filesystem::path username_path =
            std::filesystem::path(auth_directory) / "username";
        const std::filesystem::path password_path =
            std::filesystem::path(auth_directory) / "password";
        const std::filesystem::path short_password_path =
            std::filesystem::path(auth_directory) / "short-password";
        const std::filesystem::path delimiter_username_path =
            std::filesystem::path(auth_directory) / "delimiter-username";
        {
            std::ofstream username_file(username_path, std::ios::binary);
            std::ofstream password_file(password_path, std::ios::binary);
            std::ofstream short_password_file(short_password_path, std::ios::binary);
            std::ofstream delimiter_username_file(delimiter_username_path, std::ios::binary);
            username_file << "operator\n";
            password_file << "public-test-password-1234\n";
            short_password_file << "too-short\n";
            delimiter_username_file << "invalid:name\n";
        }
        result = webobs::parse_config(
            {"--scene-file", "/config/webobs/scene.json", "--listen-address", "0.0.0.0",
             "--auth-username-file", username_path.string(), "--auth-password-file",
             password_path.string(), "--control-allowed-origins", "https://monitor.example.invalid"},
            empty_environment);
        expect(result.ok() && result.config && result.config->authentication &&
                   result.config->authentication->username == "operator" &&
                   result.config->authentication->password == "public-test-password-1234" &&
                   result.config->control_allowed_origins.size() == 1,
               "file authentication must permit an explicit HTTPS control origin");

        result = webobs::parse_config(
            {"--scene-file", "/config/webobs/scene.json", "--auth-username-file",
             username_path.string()},
            empty_environment);
        expect(!result.ok(), "authentication files must be configured as a pair");

        result = webobs::parse_config(
            {"--scene-file", "/config/webobs/scene.json", "--auth-username-file",
             username_path.string(), "--auth-password-file", short_password_path.string()},
            empty_environment);
        expect(!result.ok(), "authentication passwords shorter than 16 bytes must fail");

        result = webobs::parse_config(
            {"--scene-file", "/config/webobs/scene.json", "--auth-username-file",
             delimiter_username_path.string(), "--auth-password-file", password_path.string()},
            empty_environment);
        expect(!result.ok(), "authentication usernames containing a colon must fail");

        result = webobs::parse_config(
            {"--scene-file", "/config/webobs/scene.json", "--auth-username-file", "relative-user",
             "--auth-password-file", password_path.string()},
            empty_environment);
        expect(!result.ok(), "authentication secret paths must be absolute");

        result = webobs::parse_config(
            {"--scene-file", "/config/webobs/scene.json", "--auth-username-file",
             username_path.string(), "--auth-password-file", password_path.string(),
             "--control-allowed-origins", "http://monitor.example.invalid"},
            empty_environment);
        expect(!result.ok(), "non-loopback control origins must require HTTPS");

        result = webobs::parse_config(
            {"--scene-file", "/config/webobs/scene.json", "--control-allowed-origins",
             "https://monitor.example.invalid"},
            empty_environment);
        expect(!result.ok(), "remote control origins must require authentication");
        std::error_code remove_error;
        std::filesystem::remove_all(auth_directory, remove_error);
    }

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
        {"--scene-file", "/config/webobs/scene.json", "--video-encoder", "vaapi",
         "--vaapi-device", "/dev/dri/renderD129"},
        environment({{"WEBOBS_VIDEO_ENCODER", "nvenc"},
                     {"WEBOBS_VAAPI_DEVICE", "/dev/dri/renderD128"}}));
    expect(result.ok() && result.config &&
               result.config->video_encoder == webobs::VideoEncoderPreference::vaapi &&
               result.config->vaapi_device == "/dev/dri/renderD129",
           "CLI video encoder settings must override environment values");

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

void video_encoder_tests()
{
    webobs::VideoEncoderCapabilities capabilities;
    auto selected = webobs::select_video_encoder(webobs::VideoEncoderPreference::automatic,
                                                 capabilities);
    expect(selected.selected == webobs::VideoEncoderKind::x264 && !selected.fallback,
           "automatic encoder selection must keep the software baseline without hardware");

    capabilities.vaapi = {true, true};
    selected = webobs::select_video_encoder(webobs::VideoEncoderPreference::automatic,
                                            capabilities);
    expect(selected.selected == webobs::VideoEncoderKind::vaapi && !selected.fallback,
           "automatic encoder selection must use an available VAAPI backend");

    capabilities.qsv = {true, true};
    selected = webobs::select_video_encoder(webobs::VideoEncoderPreference::automatic,
                                            capabilities);
    expect(selected.selected == webobs::VideoEncoderKind::qsv,
           "automatic encoder selection must prefer QSV over generic VAAPI");

    capabilities.nvenc = {true, true};
    selected = webobs::select_video_encoder(webobs::VideoEncoderPreference::automatic,
                                            capabilities);
    expect(selected.selected == webobs::VideoEncoderKind::nvenc,
           "automatic encoder selection must prefer NVENC when it is ready");

    capabilities.nvenc = {true, false};
    selected = webobs::select_video_encoder(webobs::VideoEncoderPreference::nvenc,
                                            capabilities);
    expect(selected.selected == webobs::VideoEncoderKind::x264 && selected.fallback,
           "an explicitly requested unavailable backend must fall back to x264");
    expect(!webobs::video_encoder_backend_ready(capabilities.nvenc),
           "a hardware device without its encoder module must not be reported ready");
}

void authentication_tests()
{
    using namespace std::chrono_literals;
    const auto start = std::chrono::steady_clock::time_point{};
    webobs::BasicAuthenticator disabled(std::nullopt, 2, 10s);
    expect(disabled.authenticate(std::nullopt, "client", start) ==
               webobs::AuthenticationDecision::allowed,
           "disabled authentication must preserve loopback compatibility");

    webobs::BasicAuthenticator authenticator(
        webobs::BasicAuthCredentials{"user", "password"}, 2, 10s);
    expect(authenticator.authenticate(std::nullopt, "client-a", start) ==
               webobs::AuthenticationDecision::credentials_required,
           "missing authorization must request credentials without consuming a failure");
    expect(authenticator.authenticate("Basic Zm9vOmJhcg==", "client-a", start) ==
               webobs::AuthenticationDecision::invalid_credentials,
           "incorrect Basic credentials must be rejected");
    expect(authenticator.authenticate("Basic Zm9vOmJhcg==", "client-a", start + 1s) ==
               webobs::AuthenticationDecision::rate_limit_started,
           "repeated incorrect credentials must trigger the bounded failure window");
    expect(authenticator.authenticate("Basic dXNlcjpwYXNzd29yZA==", "client-a", start + 2s) ==
               webobs::AuthenticationDecision::rate_limited,
           "a blocked client must remain blocked for the full failure window");
    expect(authenticator.authenticate("Basic dXNlcjpwYXNzd29yZA==", "client-b", start + 2s) ==
               webobs::AuthenticationDecision::allowed,
           "one client's failures must not block another client");
    expect(authenticator.authenticate("Basic dXNlcjpwYXNzd29yZA==", "client-a", start + 11s) ==
               webobs::AuthenticationDecision::allowed,
           "valid credentials must work after the failure window expires");
    expect(authenticator.failed_attempts() == 2,
           "authentication metrics must count invalid credentials without counting missing headers");
    expect(authenticator.authenticate("Bearer dXNlcjpwYXNzd29yZA==", "client-c", start) ==
               webobs::AuthenticationDecision::invalid_credentials,
           "non-Basic schemes must be rejected");
    expect(authenticator.authenticate("Basic dXNlcjpwYXNzd29yZA=", "client-d", start) ==
               webobs::AuthenticationDecision::invalid_credentials,
           "non-canonical Base64 must be rejected");
}

void audit_event_tests()
{
    const std::string credential_url =
        std::string("rtsp") + "://" + "audit-user:audit-password@camera.invalid/live";
    const std::string redacted_url =
        std::string("rtsp") + "://" + "***:***@camera.invalid/live";
    const std::string event = webobs::format_audit_event(
        "source_health", "rejected",
        {{"source_id", "camera-one"},
         {"detail", credential_url},
         {"Invalid-Key", "must-not-appear"}});
    expect(event.find("\"component\":\"webobsd\"") != std::string::npos &&
               event.find("\"event\":\"source_health\"") != std::string::npos &&
               event.find("camera-one") != std::string::npos,
           "audit events must use deterministic structured JSON fields");
    expect(event.find("audit-user") == std::string::npos &&
               event.find("audit-password") == std::string::npos &&
               event.find(redacted_url) != std::string::npos,
           "audit event values must pass through URL credential redaction");
    expect(event.find("Invalid-Key") == std::string::npos &&
               event.find("must-not-appear") == std::string::npos,
           "audit events must reject unstructured field names");

    const std::string long_password(300, 'p');
    const std::string long_url =
        std::string("rtsp") + "://" + "test-user:" + long_password + "@camera.invalid/live";
    const std::string long_event =
        webobs::format_audit_event("source_health", "rejected", {{"detail", long_url}});
    expect(long_event.find("test-user") == std::string::npos &&
               long_event.find(std::string(32, 'p')) == std::string::npos &&
               long_event.find(redacted_url) != std::string::npos,
           "audit event values must redact complete URLs before applying field length limits");
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
    source.sync_offset_ms = 250;
    source.monitoring = "monitor-and-output";
    source.audio_track = 3;
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
                                        .volume = 1.0,
                                        .sync_offset_ms = -125,
                                        .monitoring = "monitor-only",
                                        .audio_track = 2});
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
           "browser source settings must persist and parse in schema v3");
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
    expect(!webobs::validate_scene_document(invalid).has_value(),
           "schemaVersion 4 canvas must allow a valid custom background color");

    invalid = document;
    invalid.items.front().scale_mode = "tile";
    expect(webobs::validate_scene_document(invalid).has_value(), "unsupported item scale mode must fail validation");

    invalid = document;
    invalid.sources.front().volume = 1.01;
    expect(webobs::validate_scene_document(invalid).has_value(), "source volume above one must fail validation");

    invalid = document;
    invalid.sources.front().sync_offset_ms = 10001;
    expect(webobs::validate_scene_document(invalid).has_value(),
           "source sync offset outside ten seconds must fail validation");

    invalid = document;
    invalid.sources.front().monitoring = "speaker";
    expect(webobs::validate_scene_document(invalid).has_value(),
           "unsupported source monitoring mode must fail validation");

    invalid = document;
    invalid.sources.front().audio_track = 7;
    expect(webobs::validate_scene_document(invalid).has_value(),
           "source audio track above six must fail validation");

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
    const std::string schema_four = "\"schemaVersion\":4";
    const std::size_t schema_position = future_schema.find(schema_four);
    if (schema_position != std::string::npos)
        future_schema.replace(schema_position, schema_four.size(), "\"schemaVersion\":5");
    expect(schema_position != std::string::npos && !webobs::parse_scene_json(future_schema).ok(),
           "future scene schema versions must be rejected");

    const std::string duplicate_key =
        R"({"schemaVersion":4,"schemaVersion":4,"revision":0,"id":"main","name":"Main","canvas":{"width":1920,"height":1080,"backgroundColor":"#000000"},"sources":[],"items":[]})";
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
    const std::string current_version = "\"schemaVersion\":4";
    const std::size_t version_position = legacy_json.find(current_version);
    const std::string revision = "\"revision\":7,";
    const std::size_t revision_position = legacy_json.find(revision);
    expect(version_position != std::string::npos && revision_position != std::string::npos,
           "migration fixture must contain version and revision fields");
    if (version_position == std::string::npos || revision_position == std::string::npos)
        return;

    std::string version_two_json = compact.json;
    version_two_json.replace(version_position, current_version.size(), "\"schemaVersion\":2");
    for (const std::string_view field : {"\"audioTrack\":3,", "\"monitoring\":\"monitor-and-output\",",
                                         "\"syncOffsetMs\":250,"}) {
        const std::size_t field_position = version_two_json.find(field);
        expect(field_position != std::string::npos, "schemaVersion 2 fixture must contain removable audio fields");
        if (field_position != std::string::npos)
            version_two_json.erase(field_position, field.size());
    }
    const auto version_two_migration = webobs::migrate_scene_json(version_two_json);
    expect(version_two_migration.ok() && version_two_migration.migrated &&
               version_two_migration.document->schema_version == 4 &&
               version_two_migration.document->sources.front().sync_offset_ms == 0 &&
               version_two_migration.document->sources.front().monitoring == "off" &&
               version_two_migration.document->sources.front().audio_track == 1,
            "schemaVersion 2 must migrate to schemaVersion 4 with safe defaults");

    std::string version_one_json = version_two_json;
    version_one_json.replace(version_one_json.find("\"schemaVersion\":2"), current_version.size(),
                             "\"schemaVersion\":1");
    const auto version_one_migration = webobs::migrate_scene_json(version_one_json);
    expect(version_one_migration.ok() && version_one_migration.migrated &&
               version_one_migration.document->schema_version == 4 &&
               version_one_migration.document->revision == document.revision,
            "schemaVersion 1 must migrate to schemaVersion 4 without changing revision");

    legacy_json = version_two_json;
    legacy_json.replace(legacy_json.find("\"schemaVersion\":2"), current_version.size(),
                        "\"schemaVersion\":0");
    const std::size_t legacy_revision_position = legacy_json.find(revision);
    legacy_json.erase(legacy_revision_position, revision.size());

    const auto migrated_in_memory = webobs::migrate_scene_json(legacy_json);
    expect(migrated_in_memory.ok() && migrated_in_memory.migrated && migrated_in_memory.document->revision == 0,
           "schemaVersion 0 must migrate to revision zero");

    const std::filesystem::path legacy_path = scene_path.parent_path() / "legacy.json";
    expect(write_test_file(legacy_path, legacy_json, 0644), "legacy scene fixture must be written");
    const auto migrated_file = webobs::load_scene_file(legacy_path);
    expect(migrated_file.ok() && migrated_file.status == webobs::SceneFileStatus::migrated &&
                migrated_file.document && migrated_file.document->schema_version == 4 &&
               migrated_file.document->revision == 0,
           "legacy scene file must migrate and load");
    expect(file_mode(legacy_path) == 0600, "loaded legacy scene permissions must be tightened to 0600");
    const std::filesystem::path migration_backup(legacy_path.string() + ".pre-v4.backup");
    expect(file_mode(migration_backup) == 0600,
           "scene migration must preserve a private pre-v4 backup");
    expect(read_test_file(migration_backup) == legacy_json,
           "scene migration backup must preserve the byte-exact legacy document");
    const auto rewritten = webobs::parse_scene_json(read_test_file(legacy_path));
    expect(rewritten.ok() && rewritten.document && rewritten.document->revision == 0,
           "migrated scene must be atomically rewritten as current JSON");

    std::string future_json = compact.json;
    future_json.replace(future_json.find(current_version), current_version.size(), "\"schemaVersion\":5");
    const std::filesystem::path future_path = scene_path.parent_path() / "future.json";
    expect(write_test_file(future_path, future_json, 0600), "future scene fixture must be written");
    const auto future = webobs::load_scene_file(future_path);
    expect(!future.ok(), "future scene schema must be rejected");
    expect(read_test_file(future_path) == future_json, "rejected future scene must not be rewritten");

    const std::filesystem::path malformed_path = scene_path.parent_path() / "malformed.json";
    const std::string malformed = R"({"schemaVersion":4,"name":"sensitive-value")";
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

void studio_store_tests()
{
    char directory_template[] = "/tmp/webobs-studio-store-XXXXXX";
    const char *created_directory = mkdtemp(directory_template);
    expect(created_directory != nullptr, "studio store test directory must be created");
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

    webobs::StudioDocument original;
    original.revision = 3;
    original.program_scene_id = "program";
    original.preview_scene_id = "program";
    auto scene = valid_scene_document();
    scene.id = "program";
    scene.name = "Program";
    original.scenes.push_back(std::move(scene));

    const std::filesystem::path scene_path = root / "private" / "scene.json";
    const std::filesystem::path studio_path = webobs::default_studio_path(scene_path);
    expect(studio_path == root / "private" / "studio.json",
           "default studio file must live beside the private scene file");
    expect(!webobs::save_studio_file_atomic(studio_path, original, false).has_value(),
           "valid Studio document must be saved atomically");
    expect(file_mode(studio_path.parent_path()) == 0700,
           "Studio storage directory must use mode 0700");
    expect(file_mode(studio_path) == 0600, "Studio file must use mode 0600");

    const auto loaded = webobs::load_studio_file(studio_path);
    expect(loaded.ok() && loaded.status == webobs::StudioFileStatus::loaded &&
               loaded.document == original,
           "current Studio file must load without recovery");

    auto updated = original;
    updated.revision = 4;
    updated.scenes.front().name = "Updated Program";
    expect(!webobs::save_studio_file_atomic(studio_path, updated, true).has_value(),
           "Studio update must preserve a validated backup");
    const std::filesystem::path backup_path(studio_path.string() + ".backup");
    expect(file_mode(backup_path) == 0600, "Studio backup must use mode 0600");

    expect(write_test_file(studio_path, R"({"schemaVersion":1,"secret":"must-not-leak")", 0600),
           "corrupt Studio fixture must be written");
    const auto recovered = webobs::load_studio_file(studio_path);
    expect(recovered.ok() && recovered.status == webobs::StudioFileStatus::recovered_from_backup &&
               recovered.document == original,
           "a corrupt Studio file must recover the last validated revision");
    const auto restored = webobs::load_studio_file(studio_path);
    expect(restored.ok() && restored.status == webobs::StudioFileStatus::loaded &&
               restored.document == original,
           "Studio recovery must atomically restore the primary file");

    expect(webobs::save_studio_file_atomic("relative-studio.json", original, false).has_value(),
           "Studio save must reject a relative path");
    expect(!webobs::load_studio_file("relative-studio.json").ok(),
           "Studio load must reject a relative path");
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
        current, R"({"schemaVersion":4,"name":"do-not-echo-this-secret")", current.revision);
    expect(!secret_error.ok() && secret_error.error.find("do-not-echo-this-secret") == std::string::npos,
           "scene mutation errors must not echo secret-bearing input");
}

void studio_document_tests()
{
    webobs::SceneDocument main = valid_scene_document();
    main.id = "program";
    main.name = "Program";
    main.items.front().locked = true;
    main.items.front().rotation_degrees = 5.0;
    main.items.front().opacity = 0.8;
    main.items.front().blend_mode = "screen";
    main.sources.front().filters.push_back({
        .id = "delay-1", .kind = "delay", .enabled = true, .amount = 50.0, .value = ""});

    webobs::SceneDocument unsafe_filter = main;
    unsafe_filter.sources.front().filters.push_back({
        .id = "lut-unsafe", .kind = "lut", .enabled = true, .amount = 1.0,
        .value = "/etc/passwd"});
    expect(webobs::validate_scene_document(unsafe_filter).has_value(),
           "LUT and mask filters must not read arbitrary host paths");
    webobs::SceneDocument invalid_scaling = main;
    invalid_scaling.sources.front().filters.push_back({
        .id = "scale-invalid", .kind = "scaling", .enabled = true, .amount = 1.0,
        .value = "640;rm"});
    expect(webobs::validate_scene_document(invalid_scaling).has_value(),
           "scaling filter values must use a bounded WIDTHxHEIGHT contract");

    webobs::SceneDocument child = valid_scene_document();
    child.id = "child";
    child.name = "Child";
    child.sources.front().id = "shared-camera";
    child.items.front().source_id = "shared-camera";

    webobs::SceneSource nested;
    nested.id = "nested-child";
    nested.kind = "nested";
    nested.name = "Nested Child";
    nested.nested_scene_id = "child";
    main.sources.push_back(nested);
    main.items.push_back({
        .id = "item-nested",
        .source_id = "nested-child",
        .x = 960,
        .y = 0,
        .width = 960,
        .height = 540,
        .scale_mode = "contain",
        .crop = {},
        .z_index = 1,
        .visible = true,
        .locked = false,
        .group_id = "nested-group",
        .rotation_degrees = 0.0,
        .opacity = 1.0,
        .blend_mode = "normal",
    });

    webobs::StudioDocument studio;
    studio.revision = 9;
    studio.program_scene_id = "program";
    studio.preview_scene_id = "child";
    studio.transition = {.kind = "fade", .duration_ms = 350};
    studio.scenes = {main, child};
    expect(!webobs::validate_studio_document(studio).has_value(),
           "valid Studio document with a nested scene must pass validation");

    const auto encoded = webobs::serialize_studio_json(studio, webobs::SceneJsonView::persistence, false);
    expect(encoded.ok(), "Studio document must serialize");
    const auto parsed = webobs::parse_studio_json(encoded.json);
    expect(parsed.ok() && parsed.document == studio, "Studio JSON must round-trip byte fields");

    const auto public_json =
        webobs::serialize_studio_json(studio, webobs::SceneJsonView::public_api, false);
    expect(public_json.ok() && public_json.json.find("user:password") == std::string::npos,
           "Studio public JSON must redact RTSP credentials in every scene");

    const auto flattened = webobs::flatten_studio_scene(studio, "program");
    expect(flattened.ok() && flattened.document->sources.size() == 2 &&
               flattened.document->items.size() == 2 &&
               flattened.document->items.back().x == 1010 && flattened.document->items.back().width == 480,
           "nested Studio scenes must flatten deterministically with parent transforms");

    const auto direct = webobs::analyze_scene_capability(main, webobs::PlaybackCompositionMode::direct);
    expect(direct.selected == webobs::PlaybackCompositionMode::composite && !direct.exact &&
               !direct.reasons.empty(),
           "Direct mode must explicitly fall back when filters or advanced transforms are present");
    const auto hybrid = webobs::analyze_scene_capability(main, webobs::PlaybackCompositionMode::hybrid);
    expect(hybrid.selected == webobs::PlaybackCompositionMode::hybrid && !hybrid.exact,
           "Hybrid mode must disclose per-item Composite fallback");
    const auto capabilities = webobs::serialize_studio_capabilities_json(studio, false);
    expect(capabilities.ok() && capabilities.json.find("\"selected\":\"composite\"") != std::string::npos &&
               capabilities.json.find("user:password") == std::string::npos,
           "Studio capability contract must disclose Direct fallback without source secrets");

    webobs::StudioDocument cycle = studio;
    cycle.scenes[1].sources.clear();
    cycle.scenes[1].items.clear();
    webobs::SceneSource cycle_source = nested;
    cycle_source.id = "nested-program";
    cycle_source.nested_scene_id = "program";
    cycle.scenes[1].sources.push_back(cycle_source);
    cycle.scenes[1].items.push_back({
        .id = "item-cycle", .source_id = "nested-program", .x = 0, .y = 0, .width = 640,
        .height = 360, .scale_mode = "contain", .crop = {}, .z_index = 0, .visible = true});
    expect(webobs::validate_studio_document(cycle).has_value(),
           "nested Studio scene cycles must be rejected");

    webobs::StudioHistory history(2);
    expect(history.push("A") && history.push("B") && history.push("C") && history.undo_size() == 2,
           "Studio undo history must enforce its configured bound");
    const auto undo = history.undo("D");
    const auto second_undo = history.undo(undo.value_or(""));
    const auto redo = history.redo(second_undo.value_or(""));
    expect(undo == "C" && second_undo == "B" && redo == "C",
           "Studio undo and redo must restore byte-exact states");
}

} // namespace

int main()
{
    config_tests();
    authentication_tests();
    audit_event_tests();
    redaction_tests();
    browser_security_tests();
    scene_document_tests();
    scene_store_tests();
    studio_store_tests();
    scene_mutation_tests();
    studio_document_tests();
    video_encoder_tests();
    if (failures == 0) {
        std::cout << "All webobs unit tests passed\n";
        return 0;
    }
    std::cerr << failures << " test(s) failed\n";
    return 1;
}
