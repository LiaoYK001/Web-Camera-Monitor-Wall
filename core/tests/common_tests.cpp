#include "webobs/config.hpp"
#include "webobs/redaction.hpp"

#include <iostream>
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

} // namespace

int main()
{
    config_tests();
    redaction_tests();
    if (failures == 0) {
        std::cout << "All webobs M0 unit tests passed\n";
        return 0;
    }
    std::cerr << failures << " test(s) failed\n";
    return 1;
}
