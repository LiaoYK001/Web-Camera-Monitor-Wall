#include "webobs/redaction.hpp"
#include "webobs/scene_document.hpp"
#include "webobs/scene_store.hpp"
#include "webobs/studio_document.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>

int main(int argc, char **argv)
{
    if (argc != 3 || (std::string(argv[1]) != "validate" &&
                      std::string(argv[1]) != "validate-studio")) {
        std::cerr << "Usage: webobs-scene-tool validate <absolute-scene.json> | "
                     "validate-studio <absolute-studio.json>\n";
        return 2;
    }

    const std::filesystem::path scene_path(argv[2]);
    if (!scene_path.is_absolute() || scene_path.extension() != ".json") {
        std::cerr << "Scene path must be an absolute .json path\n";
        return 2;
    }

    if (std::string(argv[1]) == "validate-studio") {
        std::ifstream input(scene_path, std::ios::binary);
        if (!input) {
            std::cerr << "Studio validation failed: file is missing or unreadable\n";
            return 1;
        }
        const std::string content((std::istreambuf_iterator<char>(input)),
                                  std::istreambuf_iterator<char>());
        if (content.size() > webobs::maximum_scene_json_bytes) {
            std::cerr << "Studio validation failed: document is too large\n";
            return 1;
        }
        const webobs::StudioParseResult parsed = webobs::parse_studio_json(content);
        if (!parsed.ok()) {
            std::cerr << "Studio validation failed: " << webobs::redact_url_secrets(parsed.error)
                      << '\n';
            return 1;
        }
        std::cout << "Studio validation passed\n";
        return 0;
    }

    webobs::SceneFileLoadResult loaded = webobs::load_scene_file(scene_path);
    if (!loaded.ok() || !loaded.document) {
        std::cerr << "Scene validation failed: "
                  << webobs::redact_url_secrets(loaded.error.empty() ? "scene is missing" : loaded.error)
                  << '\n';
        return 1;
    }
    if (const auto error = webobs::validate_scene_document(*loaded.document)) {
        std::cerr << "Scene validation failed: " << webobs::redact_url_secrets(*error) << '\n';
        return 1;
    }
    std::cout << "Scene validation passed\n";
    return 0;
}
