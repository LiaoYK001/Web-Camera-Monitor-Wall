#include "webobs/config.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cctype>
#include <ctime>
#include <cstdlib>
#include <filesystem>
#include <iomanip>
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
    {"--output", "WEBOBS_OUTPUT", "output"},
    {"--duration-seconds", "WEBOBS_DURATION_SECONDS", "duration"},
    {"--width", "WEBOBS_WIDTH", "width"},
    {"--height", "WEBOBS_HEIGHT", "height"},
    {"--fps", "WEBOBS_FPS", "fps"},
    {"--bitrate-kbps", "WEBOBS_BITRATE_KBPS", "bitrate"},
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
    if (config.rtsp_url.empty())
        return failure("RTSP URL is required; use --rtsp-url or WEBOBS_RTSP_URL");
    if (!config.rtsp_url.starts_with("rtsp://") && !config.rtsp_url.starts_with("rtsps://"))
        return failure("RTSP URL must start with rtsp:// or rtsps://");

    config.output_path = values.contains("output") ? values["output"] : timestamped_output_path();
    if (config.output_path.empty())
        return failure("output path must not be empty");
    const std::string extension = lowercase(std::filesystem::path(config.output_path).extension().string());
    if (extension != ".mp4")
        return failure("output path must use the .mp4 extension");

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

Required:
  --rtsp-url <url>                 RTSP input URL (or WEBOBS_RTSP_URL)

Options:
  --output <path>                  MP4 output path (default: UTC timestamp under /recordings)
  --duration-seconds <n>           Stop after n seconds; 0 waits for a signal (default: 0)
  --width <n>                      Even output width (default: 1920)
  --height <n>                     Even output height (default: 1080)
  --fps <n>                        Output frames per second (default: 30)
  --bitrate-kbps <n>               x264 CBR bitrate (default: 6000)
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
    return std::string("webobsd ") + WEBOBS_VERSION + " (M0, OBS 32.1.2)";
}

} // namespace webobs
