#include "webobs/config.hpp"
#include "webobs/obs_engine.hpp"
#include "webobs/redaction.hpp"
#include "webobs/scene_document.hpp"
#include "webobs/scene_store.hpp"

#include <curl/curl.h>

#include <iostream>
#include <string>
#include <utility>
#include <vector>

namespace {

webobs::SceneDocument bootstrap_scene(const webobs::Config &config)
{
    webobs::SceneDocument document;
    document.canvas.width = config.width;
    document.canvas.height = config.height;
    webobs::SceneSource source;
    source.id = "camera-1";
    source.name = "Camera 1";
    source.rtsp_url = config.rtsp_url;
    source.transport = config.rtsp_transport;
    source.muted = true;
    source.volume = 1.0;
    document.sources.push_back(std::move(source));
    document.items.push_back({
        .id = "item-camera-1",
        .source_id = "camera-1",
        .x = 0,
        .y = 0,
        .width = config.width,
        .height = config.height,
        .scale_mode = "contain",
        .crop = {},
        .z_index = 0,
        .visible = true,
    });
    return document;
}

} // namespace

int main(int argc, char **argv)
{
    std::vector<std::string> arguments;
    arguments.reserve(argc > 1 ? static_cast<std::size_t>(argc - 1) : 0);
    for (int index = 1; index < argc; ++index)
        arguments.emplace_back(argv[index]);

    const webobs::ParseResult result = webobs::parse_config(arguments, webobs::process_environment);
    if (!result.ok()) {
        std::cerr << "configuration error: " << webobs::redact_url_secrets(result.error) << "\n\n"
                  << webobs::usage_text();
        return static_cast<int>(webobs::ExitCode::invalid_config);
    }
    if (result.action == webobs::ParseAction::show_help) {
        std::cout << webobs::usage_text();
        return 0;
    }
    if (result.action == webobs::ParseAction::show_version) {
        std::cout << webobs::version_text() << '\n';
        return 0;
    }

    const webobs::Config &config = *result.config;
    webobs::SceneDocument document;
    if (!config.scene_file.empty()) {
        webobs::SceneFileLoadResult loaded = webobs::load_scene_file(config.scene_file);
        if (!loaded.ok()) {
            std::cerr << "scene storage error: " << webobs::redact_url_secrets(loaded.error) << '\n';
            return static_cast<int>(webobs::ExitCode::scene_store_failed);
        }
        if (loaded.document) {
            document = std::move(*loaded.document);
        } else {
            document = config.rtsp_url.empty() ? webobs::SceneDocument{} : bootstrap_scene(config);
            if (const auto save_error = webobs::save_scene_file_atomic(config.scene_file, document)) {
                std::cerr << "scene storage error: " << webobs::redact_url_secrets(*save_error) << '\n';
                return static_cast<int>(webobs::ExitCode::scene_store_failed);
            }
        }
    } else {
        document = bootstrap_scene(config);
    }

    if (const auto validation_error = webobs::validate_scene_document(document)) {
        std::cerr << "configuration error: " << *validation_error << '\n';
        return static_cast<int>(webobs::ExitCode::invalid_config);
    }
    if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) {
        std::cerr << "runtime error: could not initialize the HTTP signaling library\n";
        return static_cast<int>(webobs::ExitCode::control_server_failed);
    }
    const int exit_code = static_cast<int>(webobs::run_obs_engine(config, document));
    curl_global_cleanup();
    return exit_code;
}
