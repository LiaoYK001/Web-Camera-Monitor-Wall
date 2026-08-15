#pragma once

#include "webobs/studio_document.hpp"

#include <filesystem>
#include <optional>
#include <string>

namespace webobs {

enum class StudioFileStatus {
    loaded,
    not_found,
    recovered_from_backup,
};

struct StudioFileLoadResult {
    StudioFileStatus status = StudioFileStatus::not_found;
    std::optional<StudioDocument> document;
    std::string error;

    [[nodiscard]] bool ok() const { return error.empty(); }
};

std::filesystem::path default_studio_path(const std::filesystem::path &scene_path);
std::optional<std::string> save_studio_file_atomic(const std::filesystem::path &path,
                                                   const StudioDocument &document,
                                                   bool preserve_backup = true);
StudioFileLoadResult load_studio_file(const std::filesystem::path &path);

} // namespace webobs
