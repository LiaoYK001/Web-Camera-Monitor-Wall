#include "webobs/config.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cctype>
#include <ctime>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <map>
#include <sstream>
#include <system_error>
#include <utility>

namespace webobs {
namespace {

struct SettingSpec {
    const char *flag;
    const char *environment;
    const char *key;
};

constexpr SettingSpec setting_specs[] = {
    {"--rtsp-url", "WEBOBS_RTSP_URL", "rtsp_url"},
    {"--scene-file", "WEBOBS_SCENE_FILE", "scene_file"},
    {"--listen-address", "WEBOBS_LISTEN_ADDRESS", "listen_address"},
    {"--http-port", "WEBOBS_HTTP_PORT", "http_port"},
    {"--allow-insecure-remote", "WEBOBS_ALLOW_INSECURE_REMOTE", "allow_insecure_remote"},
    {"--auth-username-file", "WEBOBS_AUTH_USERNAME_FILE", "auth_username_file"},
    {"--auth-password-file", "WEBOBS_AUTH_PASSWORD_FILE", "auth_password_file"},
    {"--auth-failure-limit", "WEBOBS_AUTH_FAILURE_LIMIT", "auth_failure_limit"},
    {"--auth-failure-window-seconds", "WEBOBS_AUTH_FAILURE_WINDOW_SECONDS", "auth_failure_window"},
    {"--session-database", "WEBOBS_SESSION_DATABASE", "session_database"},
    {"--session-inactivity-seconds", "WEBOBS_SESSION_INACTIVITY_SECONDS", "session_inactivity"},
    {"--session-cookie-secure", "WEBOBS_SESSION_COOKIE_SECURE", "session_cookie_secure"},
    {"--control-allowed-origins", "WEBOBS_CONTROL_ALLOWED_ORIGINS", "control_allowed_origins"},
    {"--pwa-media-allowed-origins", "WEBOBS_PWA_MEDIA_ALLOWED_ORIGINS", "pwa_media_allowed_origins"},
    {"--source-stale-seconds", "WEBOBS_SOURCE_STALE_SECONDS", "source_stale_seconds"},
    {"--source-recovery-base-seconds", "WEBOBS_SOURCE_RECOVERY_BASE_SECONDS", "source_recovery_base"},
    {"--source-recovery-max-seconds", "WEBOBS_SOURCE_RECOVERY_MAX_SECONDS", "source_recovery_max"},
    {"--webrtc-enabled", "WEBOBS_WEBRTC_ENABLED", "webrtc_enabled"},
    {"--composite-enabled", "WEBOBS_COMPOSITE_ENABLED", "composite_enabled"},
    {"--nvr-enabled", "WEBOBS_NVR_ENABLED", "nvr_enabled"},
    {"--camera-registry-enabled", "WEBOBS_CAMERA_REGISTRY_ENABLED", "camera_registry_enabled"},
    {"--whip-url", "WEBOBS_WHIP_URL", "whip_url"},
    {"--browser-allowed-origins", "WEBOBS_BROWSER_ALLOWED_ORIGINS", "browser_allowed_origins"},
    {"--browser-allow-private-networks", "WEBOBS_BROWSER_ALLOW_PRIVATE_NETWORKS",
     "browser_allow_private_networks"},
    {"--output", "WEBOBS_OUTPUT", "output"},
    {"--duration-seconds", "WEBOBS_DURATION_SECONDS", "duration"},
    {"--width", "WEBOBS_WIDTH", "width"},
    {"--height", "WEBOBS_HEIGHT", "height"},
    {"--fps", "WEBOBS_FPS", "fps"},
    {"--bitrate-kbps", "WEBOBS_BITRATE_KBPS", "bitrate"},
    {"--video-encoder", "WEBOBS_VIDEO_ENCODER", "video_encoder"},
    {"--vaapi-device", "WEBOBS_VAAPI_DEVICE", "vaapi_device"},
    {"--renderer", "WEBOBS_RENDERER", "renderer"},
    {"--hardware-decode", "WEBOBS_HARDWARE_DECODE", "hardware_decode"},
    {"--connect-timeout-seconds", "WEBOBS_CONNECT_TIMEOUT_SECONDS", "connect_timeout"},
    {"--rtsp-transport", "WEBOBS_RTSP_TRANSPORT", "transport"},
    {"--log-level", "WEBOBS_LOG_LEVEL", "log_level"},
};

const SettingSpec *find_flag(std::string_view flag)
{
    for (const auto &spec : setting_specs) {
        if (flag == spec.flag)
            return &spec;
    }
    return nullptr;
}

std::string timestamped_output_path()
{
    const auto now = std::chrono::system_clock::now();
    const std::time_t value = std::chrono::system_clock::to_time_t(now);
    const auto milliseconds =
        std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count() % 1000;
    std::tm utc{};
#ifdef _WIN32
    gmtime_s(&utc, &value);
#else
    gmtime_r(&value, &utc);
#endif
    std::ostringstream name;
    name << "/recordings/webobs-" << std::put_time(&utc, "%Y%m%d-%H%M%S") << '-'
         << std::setfill('0') << std::setw(3) << milliseconds << ".mp4";
    return name.str();
}

bool parse_integer(std::string_view value, int minimum, int maximum, int &target)
{
    int parsed = 0;
    const auto *begin = value.data();
    const auto *end = value.data() + value.size();
    const auto result = std::from_chars(begin, end, parsed);
    if (result.ec != std::errc{} || result.ptr != end || parsed < minimum || parsed > maximum)
        return false;
    target = parsed;
    return true;
}

std::string lowercase(std::string value)
{
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}

bool parse_boolean(std::string_view value, bool &target)
{
    const std::string normalized = lowercase(std::string(value));
    if (normalized == "1" || normalized == "true" || normalized == "yes") {
        target = true;
        return true;
    }
    if (normalized == "0" || normalized == "false" || normalized == "no") {
        target = false;
        return true;
    }
    return false;
}

bool valid_whip_url(std::string_view value)
{
    const std::size_t scheme_size = value.starts_with("http://") ? 7 : value.starts_with("https://") ? 8 : 0;
    if (scheme_size == 0 || value.size() == scheme_size || value.find_first_of("?#") != std::string_view::npos)
        return false;
    if (std::any_of(value.begin(), value.end(), [](unsigned char character) {
            return std::iscntrl(character) || std::isspace(character);
        }))
        return false;

    const std::size_t authority_end = value.find('/', scheme_size);
    const std::string_view authority = value.substr(scheme_size, authority_end - scheme_size);
    return !authority.empty() && authority.find('@') == std::string_view::npos;
}

bool parse_origins(std::string_view value, std::string_view setting,
                   std::vector<std::string> &origins, std::string &error)
{
    if (value.size() > 8192) {
        error = std::string(setting) + " exceeds the configured length limit";
        return false;
    }
    std::size_t cursor = 0;
    while (cursor < value.size()) {
        const std::size_t comma = value.find(',', cursor);
        const std::size_t end = comma == std::string_view::npos ? value.size() : comma;
        std::string_view entry = value.substr(cursor, end - cursor);
        while (!entry.empty() && std::isspace(static_cast<unsigned char>(entry.front())))
            entry.remove_prefix(1);
        while (!entry.empty() && std::isspace(static_cast<unsigned char>(entry.back())))
            entry.remove_suffix(1);
        if (entry.empty()) {
            error = std::string(setting) + " must be a comma-separated list without empty entries";
            return false;
        }
        std::string normalized;
        if (const auto origin_error = normalize_browser_origin(entry, normalized)) {
            error = *origin_error;
            return false;
        }
        if (std::find(origins.begin(), origins.end(), normalized) == origins.end())
            origins.push_back(std::move(normalized));
        if (origins.size() > 32) {
            error = std::string(setting) + " must contain at most 32 origins";
            return false;
        }
        if (comma == std::string_view::npos)
            break;
        cursor = comma + 1;
    }
    return true;
}

bool loopback_control_origin(std::string_view origin)
{
    const BrowserUrlResult parsed = parse_browser_url(origin);
    if (!parsed.ok())
        return false;
    const std::string &host = parsed.parts->host;
    return host == "localhost" || host == "127.0.0.1" || host == "::1";
}

std::optional<std::string> read_auth_secret(std::string_view path_value, bool username,
                                           std::string &error)
{
    const std::filesystem::path path(path_value);
    const std::string field = username ? "auth-username-file" : "auth-password-file";
    if (!path.is_absolute()) {
        error = field + " must use an absolute path";
        return std::nullopt;
    }
    std::error_code filesystem_error;
    if (!std::filesystem::is_regular_file(path, filesystem_error) || filesystem_error) {
        error = field + " must reference a readable regular file";
        return std::nullopt;
    }
    const auto size = std::filesystem::file_size(path, filesystem_error);
    if (filesystem_error || size > 4096) {
        error = field + " exceeds the four KiB safety limit";
        return std::nullopt;
    }
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        error = field + " could not be read";
        return std::nullopt;
    }
    std::string value((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    if (!value.empty() && value.back() == '\n') {
        value.pop_back();
        if (!value.empty() && value.back() == '\r')
            value.pop_back();
    }
    const std::size_t minimum = username ? 1 : 16;
    const std::size_t maximum = username ? 64 : 256;
    if (value.size() < minimum || value.size() > maximum) {
        error = field + (username ? " must contain 1 to 64 bytes" : " must contain 16 to 256 bytes");
        return std::nullopt;
    }
    for (unsigned char character : value) {
        const bool invalid_control = character < 0x20 || character == 0x7f;
        const bool invalid_username = username && (character > 0x7e || character == ':');
        if (invalid_control || invalid_username) {
            error = field + " contains a forbidden control or delimiter byte";
            return std::nullopt;
        }
    }
    return value;
}

ParseResult failure(std::string message)
{
    ParseResult result;
    result.error = std::move(message);
    return result;
}

} // namespace

ParseResult parse_config(const std::vector<std::string> &arguments, const EnvironmentLookup &environment)
{
    std::map<std::string, std::string> values = {
        {"duration", "0"},          {"width", "1920"},       {"height", "1080"},
        {"fps", "30"},             {"bitrate", "6000"},     {"connect_timeout", "20"},
        {"transport", "tcp"},       {"log_level", "info"},
        {"video_encoder", "auto"},  {"vaapi_device", "/dev/dri/renderD128"},
        {"renderer", "auto"},       {"hardware_decode", "auto"},
        {"scene_file", "/config/webobs/scene.json"},
        {"listen_address", "127.0.0.1"}, {"http_port", "8080"},
        {"allow_insecure_remote", "false"},
        {"auth_username_file", ""}, {"auth_password_file", ""},
        {"auth_failure_limit", "5"}, {"auth_failure_window", "60"},
        {"session_database", "/config/webobs/auth-sessions.db"},
        {"session_inactivity", "604800"}, {"session_cookie_secure", "true"},
        {"control_allowed_origins", ""},
        {"pwa_media_allowed_origins", ""},
        {"source_stale_seconds", "10"}, {"source_recovery_base", "5"},
        {"source_recovery_max", "60"},
        {"webrtc_enabled", "false"}, {"composite_enabled", "false"}, {"nvr_enabled", "false"},
        {"camera_registry_enabled", "true"},
        {"whip_url", "http://127.0.0.1:8889/program/whip"},
        {"browser_allowed_origins", ""}, {"browser_allow_private_networks", "false"},
    };

    for (const auto &spec : setting_specs) {
        if (const auto value = environment(spec.environment); value && !value->empty())
            values[spec.key] = *value;
    }

    ParseAction action = ParseAction::run;
    for (std::size_t index = 0; index < arguments.size(); ++index) {
        const std::string &argument = arguments[index];
        if (argument == "--help") {
            action = ParseAction::show_help;
            continue;
        }
        if (argument == "--version") {
            action = ParseAction::show_version;
            continue;
        }

        const SettingSpec *spec = find_flag(argument);
        if (!spec)
            return failure("unknown argument: " + argument);
        if (index + 1 >= arguments.size())
            return failure("missing value for " + argument);
        values[spec->key] = arguments[++index];
    }

    if (action != ParseAction::run) {
        ParseResult result;
        result.action = action;
        return result;
    }

    Config config;
    if (const auto iterator = values.find("rtsp_url"); iterator != values.end())
        config.rtsp_url = iterator->second;
    if (const auto iterator = values.find("scene_file"); iterator != values.end())
        config.scene_file = iterator->second;
    if (!config.rtsp_url.empty() && !config.rtsp_url.starts_with("rtsp://") &&
        !config.rtsp_url.starts_with("rtsps://"))
        return failure("RTSP URL must start with rtsp:// or rtsps://");
    if (!config.scene_file.empty()) {
        const std::filesystem::path scene_path(config.scene_file);
        if (!scene_path.is_absolute())
            return failure("scene-file must use an absolute path");
        if (lowercase(scene_path.extension().string()) != ".json")
            return failure("scene-file must use the .json extension");
    }

    config.listen_address = lowercase(values["listen_address"]);
    if (config.listen_address != "127.0.0.1" && config.listen_address != "::1" &&
        config.listen_address != "0.0.0.0" && config.listen_address != "::")
        return failure("listen-address must be 127.0.0.1, ::1, 0.0.0.0, or ::");
    if (!parse_integer(values["http_port"], 0, 65535, config.http_port))
        return failure("http-port must be between 0 and 65535");
    if (!parse_boolean(values["allow_insecure_remote"], config.allow_insecure_remote))
        return failure("allow-insecure-remote must be true or false");
    const bool loopback = config.listen_address == "127.0.0.1" || config.listen_address == "::1";

    if (!parse_integer(values["auth_failure_limit"], 1, 100, config.auth_failure_limit))
        return failure("auth-failure-limit must be between 1 and 100");
    if (!parse_integer(values["auth_failure_window"], 1, 3600, config.auth_failure_window_seconds))
        return failure("auth-failure-window-seconds must be between 1 and 3600");
    config.session_database = values["session_database"];
    if (!std::filesystem::path(config.session_database).is_absolute() ||
        lowercase(std::filesystem::path(config.session_database).extension().string()) != ".db")
        return failure("session-database must be an absolute .db path");
    if (!parse_integer(values["session_inactivity"], 300, 2592000, config.session_inactivity_seconds))
        return failure("session-inactivity-seconds must be between 300 and 2592000");
    if (!parse_boolean(values["session_cookie_secure"], config.session_cookie_secure))
        return failure("session-cookie-secure must be true or false");
    const bool username_file_set = !values["auth_username_file"].empty();
    const bool password_file_set = !values["auth_password_file"].empty();
    if (username_file_set != password_file_set)
        return failure("auth-username-file and auth-password-file must be configured together");
    if (username_file_set) {
        std::string secret_error;
        const auto username = read_auth_secret(values["auth_username_file"], true, secret_error);
        if (!username)
            return failure(std::move(secret_error));
        const auto password = read_auth_secret(values["auth_password_file"], false, secret_error);
        if (!password)
            return failure(std::move(secret_error));
        config.authentication = BasicAuthCredentials{*username, *password};
    }
    if (!values["control_allowed_origins"].empty()) {
        std::string origin_error;
        if (!parse_origins(values["control_allowed_origins"], "control-allowed-origins",
                           config.control_allowed_origins, origin_error))
            return failure(std::move(origin_error));
        if (!config.authentication)
            return failure("control-allowed-origins requires file-based authentication");
        for (const std::string &origin : config.control_allowed_origins) {
            if (!origin.starts_with("https://") && !loopback_control_origin(origin))
                return failure("non-loopback control origins must use HTTPS");
        }
    }
    if (!values["pwa_media_allowed_origins"].empty()) {
        std::string origin_error;
        if (!parse_origins(values["pwa_media_allowed_origins"], "pwa-media-allowed-origins",
                           config.pwa_media_allowed_origins, origin_error))
            return failure(std::move(origin_error));
        for (const std::string &origin : config.pwa_media_allowed_origins) {
            if (!origin.starts_with("https://"))
                return failure("PWA media origins must use HTTPS");
        }
    }
    if (config.http_port != 0 && !loopback && !config.allow_insecure_remote && !config.authentication)
        return failure("non-loopback HTTP listening requires authentication or --allow-insecure-remote true");

    if (!parse_integer(values["source_stale_seconds"], 2, 300, config.source_stale_seconds))
        return failure("source-stale-seconds must be between 2 and 300");
    if (!parse_integer(values["source_recovery_base"], 1, 300,
                       config.source_recovery_base_seconds))
        return failure("source-recovery-base-seconds must be between 1 and 300");
    if (!parse_integer(values["source_recovery_max"], 1, 3600,
                       config.source_recovery_max_seconds))
        return failure("source-recovery-max-seconds must be between 1 and 3600");
    if (config.source_recovery_max_seconds < config.source_recovery_base_seconds)
        return failure("source-recovery-max-seconds must not be less than source-recovery-base-seconds");

    if (!parse_boolean(values["webrtc_enabled"], config.webrtc_enabled))
        return failure("webrtc-enabled must be true or false");
    if (!parse_boolean(values["composite_enabled"], config.composite_enabled))
        return failure("composite-enabled must be true or false");
    if (config.composite_enabled && !config.webrtc_enabled)
        return failure("composite-enabled requires webrtc-enabled true");
    if (!parse_boolean(values["nvr_enabled"], config.nvr_enabled))
        return failure("nvr-enabled must be true or false");
    if (!parse_boolean(values["camera_registry_enabled"], config.camera_registry_enabled))
        return failure("camera-registry-enabled must be true or false");
    config.whip_url = values["whip_url"];
    if (config.webrtc_enabled && !valid_whip_url(config.whip_url))
        return failure("whip-url must be an absolute HTTP(S) URL without credentials, query parameters, or fragments");

    if (!parse_boolean(values["browser_allow_private_networks"],
                       config.browser_security.allow_private_networks))
        return failure("browser-allow-private-networks must be true or false");
    if (!values["browser_allowed_origins"].empty()) {
        std::string browser_origin_error;
        if (!parse_origins(values["browser_allowed_origins"], "browser-allowed-origins",
                           config.browser_security.allowed_origins, browser_origin_error))
            return failure(std::move(browser_origin_error));
    }

    if (values.contains("output"))
        config.output_path = values["output"];
    else if (!config.rtsp_url.empty())
        config.output_path = timestamped_output_path();
    if (!config.output_path.empty()) {
        const std::string extension = lowercase(std::filesystem::path(config.output_path).extension().string());
        if (extension != ".mp4")
            return failure("output path must use the .mp4 extension");
    }

    if (!parse_integer(values["duration"], 0, 604800, config.duration_seconds))
        return failure("duration-seconds must be between 0 and 604800");
    if (!parse_integer(values["width"], 16, 8192, config.width) || config.width % 2 != 0)
        return failure("width must be an even number between 16 and 8192");
    if (!parse_integer(values["height"], 16, 8192, config.height) || config.height % 2 != 0)
        return failure("height must be an even number between 16 and 8192");
    if (!parse_integer(values["fps"], 1, 120, config.fps))
        return failure("fps must be between 1 and 120");
    if (!parse_integer(values["bitrate"], 50, 100000, config.bitrate_kbps))
        return failure("bitrate-kbps must be between 50 and 100000");
    const std::string video_encoder = lowercase(values["video_encoder"]);
    if (video_encoder == "auto")
        config.video_encoder = VideoEncoderPreference::automatic;
    else if (video_encoder == "x264")
        config.video_encoder = VideoEncoderPreference::x264;
    else if (video_encoder == "vaapi")
        config.video_encoder = VideoEncoderPreference::vaapi;
    else if (video_encoder == "qsv")
        config.video_encoder = VideoEncoderPreference::qsv;
    else if (video_encoder == "nvenc")
        config.video_encoder = VideoEncoderPreference::nvenc;
    else
        return failure("video-encoder must be auto, x264, vaapi, qsv, or nvenc");
    const std::string renderer = lowercase(values["renderer"]);
    if (renderer == "auto")
        config.renderer = RendererPreference::automatic;
    else if (renderer == "hardware")
        config.renderer = RendererPreference::hardware;
    else if (renderer == "software")
        config.renderer = RendererPreference::software;
    else
        return failure("renderer must be auto, hardware, or software");
    const std::string hardware_decode = lowercase(values["hardware_decode"]);
    if (hardware_decode == "auto")
        config.hardware_decode = HardwareDecodePreference::automatic;
    else if (hardware_decode == "on")
        config.hardware_decode = HardwareDecodePreference::on;
    else if (hardware_decode == "off")
        config.hardware_decode = HardwareDecodePreference::off;
    else
        return failure("hardware-decode must be auto, on, or off");
    config.vaapi_device = values["vaapi_device"];
    const std::filesystem::path vaapi_path(config.vaapi_device);
    const std::string vaapi_filename = vaapi_path.filename().string();
    if (!vaapi_path.is_absolute() || vaapi_path.parent_path() != "/dev/dri" ||
        !vaapi_filename.starts_with("renderD") || vaapi_filename.size() <= 7 ||
        vaapi_filename.size() > 16 ||
        !std::all_of(vaapi_filename.begin() + 7, vaapi_filename.end(),
                     [](unsigned char character) { return std::isdigit(character); }))
        return failure("vaapi-device must be an absolute /dev/dri/renderD<n> path");
    if (!parse_integer(values["connect_timeout"], 1, 300, config.connect_timeout_seconds))
        return failure("connect-timeout-seconds must be between 1 and 300");

    config.rtsp_transport = lowercase(values["transport"]);
    if (config.rtsp_transport != "tcp" && config.rtsp_transport != "udp")
        return failure("rtsp-transport must be tcp or udp");

    const std::string level = lowercase(values["log_level"]);
    if (level == "error")
        config.log_level = LogLevel::error;
    else if (level == "warn" || level == "warning")
        config.log_level = LogLevel::warning;
    else if (level == "info")
        config.log_level = LogLevel::info;
    else if (level == "debug")
        config.log_level = LogLevel::debug;
    else
        return failure("log-level must be error, warn, info, or debug");

    ParseResult result;
    result.config = std::move(config);
    return result;
}

std::optional<std::string> process_environment(std::string_view name)
{
    const std::string key(name);
    if (const char *value = std::getenv(key.c_str()))
        return std::string(value);
    return std::nullopt;
}

std::string usage_text()
{
    return R"(Usage: webobsd [options]

Bootstrap (optional):
  --rtsp-url <url>                 Bootstrap RTSP URL when no saved scene exists
  --scene-file <path>              Absolute scene JSON path (or WEBOBS_SCENE_FILE)

An empty deployment creates the default scene file with no cameras. A saved
scene takes precedence; an RTSP URL is used only to create a missing scene.

Options:
  --listen-address <address>        HTTP bind address (default: 127.0.0.1)
  --http-port <n>                   HTTP/WebSocket port; 0 disables (default: 8080)
  --allow-insecure-remote <bool>    Legacy unauthenticated non-loopback opt-in (unsafe)
  --auth-username-file <path>       Absolute file containing the Basic Auth username
  --auth-password-file <path>       Absolute file containing a password of at least 16 bytes
  --auth-failure-limit <n>          Invalid attempts per client/window (default: 5)
  --auth-failure-window-seconds <n> Failure window and lockout duration (default: 60)
  --session-database <path>        SQLite WAL session database
  --session-inactivity-seconds <n> Sliding expiry (default: 604800 / 7 days)
  --session-cookie-secure <bool>   Require HTTPS for browser session cookie (default: true)
  --control-allowed-origins <csv>   Authenticated HTTPS origins allowed beyond loopback
  --pwa-media-allowed-origins <csv> Exact HTTPS camera origins allowed by the PWA CSP
  --source-stale-seconds <n>        No-new-frame threshold (default: 10)
  --source-recovery-base-seconds <n> Initial RTSP restart backoff (default: 5)
  --source-recovery-max-seconds <n>  Maximum RTSP restart backoff (default: 60)
  --webrtc-enabled <bool>          Publish the program through WHIP (default: false)
  --composite-enabled <bool>       Activate OBS sources and Program WHIP (default: false)
  --nvr-enabled <bool>             Run the independent per-camera NVR service (default: false)
  --camera-registry-enabled <bool> Run the SQLite Camera Registry service (default: true)
  --whip-url <url>                 WHIP publish URL (default: internal MediaMTX)
  --browser-allowed-origins <csv>  Exact HTTP(S) origins permitted for browser sources
  --browser-allow-private-networks <bool>
                                   Permit allowlisted local/private destinations (default: false)
  --output <path>                  MP4 output path (RTSP bootstrap defaults to a UTC timestamp)
  --duration-seconds <n>           Stop after n seconds; 0 waits for a signal (default: 0)
  --width <n>                      Even output width (default: 1920)
  --height <n>                     Even output height (default: 1080)
  --fps <n>                        Output frames per second (default: 30)
  --bitrate-kbps <n>               H.264 CBR bitrate (default: 6000)
  --video-encoder <backend>        auto, x264, vaapi, qsv, or nvenc (default: auto)
  --vaapi-device <path>            VAAPI render node (default: /dev/dri/renderD128)
  --renderer <mode>                auto, hardware, or software (default: auto)
  --hardware-decode <mode>         auto, on, or off (default: auto)
  --connect-timeout-seconds <n>    RTSP first-frame timeout (default: 20)
  --rtsp-transport <tcp|udp>       RTSP transport (default: tcp)
  --log-level <level>              error, warn, info, or debug (default: info)
  --help                           Show this help
  --version                        Show the version

Command-line values override WEBOBS_* environment values.
)";
}

std::string version_text()
{
    return std::string("webobsd ") + WEBOBS_VERSION + " (" + WEBOBS_MILESTONE + ", OBS 32.1.2)";
}

std::string_view renderer_preference_name(RendererPreference preference)
{
    switch (preference) {
    case RendererPreference::automatic: return "auto";
    case RendererPreference::hardware: return "hardware";
    case RendererPreference::software: return "software";
    }
    return "unknown";
}

std::string_view hardware_decode_preference_name(HardwareDecodePreference preference)
{
    switch (preference) {
    case HardwareDecodePreference::automatic: return "auto";
    case HardwareDecodePreference::on: return "on";
    case HardwareDecodePreference::off: return "off";
    }
    return "unknown";
}

} // namespace webobs
