#pragma once

#include "webobs/scene_document.hpp"

#include <filesystem>
#include <optional>
#include <string>
#include <string_view>

namespace webobs {

struct SceneMigrationResult {
    std::optional<SceneDocument> document;
    bool migrated = false;
    std::string error;

    [[nodiscard]] bool ok() const { return document.has_value() && error.empty(); }
};

enum class SceneFileStatus {
    loaded,
    not_found,
    migrated,
};

struct SceneFileLoadResult {
    SceneFileStatus status = SceneFileStatus::not_found;
    std::optional<SceneDocument> document;
    std::string error;

    [[nodiscard]] bool ok() const { return error.empty(); }
};

// Migrate validated historical JSON into the current in-memory document.
// schemaVersion 0 was the pre-release M1 shape: it matches v1 except that the
// revision field is absent. Unversioned and future documents are rejected.
SceneMigrationResult migrate_scene_json(std::string_view json);

// Scene files must use an absolute path with an explicit parent directory.
// The directory is restricted to 0700 and files are written as 0600.
std::optional<std::string> save_scene_file_atomic(const std::filesystem::path &path,
                                                  const SceneDocument &document);
SceneFileLoadResult load_scene_file(const std::filesystem::path &path);

} // namespace webobs
