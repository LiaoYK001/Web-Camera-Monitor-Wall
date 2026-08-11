#pragma once

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs {

enum class LogLevel {
    error = 100,
    warning = 200,
    info = 300,
    debug = 400,
};

struct Config {
    std::string rtsp_url;
    std::string scene_file;
    std::string output_path;
    int duration_seconds = 0;
    int width = 1920;
    int height = 1080;
    int fps = 30;
    int bitrate_kbps = 6000;
    int connect_timeout_seconds = 20;
    std::string rtsp_transport = "tcp";
    LogLevel log_level = LogLevel::info;
};

enum class ParseAction {
    run,
    show_help,
    show_version,
};

struct ParseResult {
    ParseAction action = ParseAction::run;
    std::optional<Config> config;
    std::string error;

    [[nodiscard]] bool ok() const { return error.empty(); }
};

using EnvironmentLookup = std::function<std::optional<std::string>(std::string_view)>;

ParseResult parse_config(const std::vector<std::string> &arguments, const EnvironmentLookup &environment);
std::optional<std::string> process_environment(std::string_view name);
std::string usage_text();
std::string version_text();

} // namespace webobs
