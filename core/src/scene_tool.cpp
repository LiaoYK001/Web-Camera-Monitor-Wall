#include "webobs/redaction.hpp"
#include "webobs/scene_document.hpp"
#include "webobs/scene_store.hpp"

#include <filesystem>
#include <iostream>
#include <string>

int main(int argc, char **argv)
{
    if (argc != 3 || std::string(argv[1]) != "validate") {
        std::cerr << "Usage: webobs-scene-tool validate <absolute-scene.json>\n";
        return 2;
    }

    const std::filesystem::path scene_path(argv[2]);
    if (!scene_path.is_absolute() || scene_path.extension() != ".json") {
        std::cerr << "Scene path must be an absolute .json path\n";
        return 2;
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
