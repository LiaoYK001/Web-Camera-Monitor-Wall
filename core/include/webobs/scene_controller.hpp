#pragma once

#include "webobs/obs_scene_runtime.hpp"
#include "webobs/scene_document.hpp"

#include <cstdint>
#include <filesystem>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>

namespace webobs {

struct SceneSnapshot {
    std::uint64_t revision = 0;
    std::string public_json;
    std::string error;

    [[nodiscard]] bool ok() const { return !public_json.empty() && error.empty(); }
};

enum class SceneUpdateStatus {
    success,
    precondition_required,
    revision_conflict,
    invalid_document,
    runtime_rejected,
    persistence_unavailable,
    persistence_failed,
};

struct SceneUpdateResult {
    SceneUpdateStatus status = SceneUpdateStatus::invalid_document;
    std::uint64_t revision = 0;
    std::string public_json;
    std::string error;

    [[nodiscard]] bool ok() const { return status == SceneUpdateStatus::success && !public_json.empty(); }
};

class SceneController {
public:
    SceneController(SceneDocument document, std::filesystem::path scene_file, ObsSceneRuntime &runtime);

    [[nodiscard]] SceneSnapshot snapshot() const;
    [[nodiscard]] SceneDocument private_document_snapshot() const;
    SceneUpdateResult replace(std::string_view candidate_json,
                              std::optional<std::uint64_t> expected_revision);

private:
    mutable std::mutex mutex_;
    SceneDocument document_;
    std::filesystem::path scene_file_;
    ObsSceneRuntime &runtime_;
};

} // namespace webobs
