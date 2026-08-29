#pragma once

#include "webobs/scene_controller.hpp"
#include "webobs/studio_document.hpp"

#include <cstdint>
#include <filesystem>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>

namespace webobs {

enum class StudioUpdateStatus {
    success,
    precondition_required,
    revision_conflict,
    invalid_document,
    runtime_rejected,
    persistence_failed,
    history_empty,
};

struct StudioUpdateResult {
    StudioUpdateStatus status = StudioUpdateStatus::invalid_document;
    std::uint64_t revision = 0;
    std::string public_json;
    std::string error;

    [[nodiscard]] bool ok() const { return status == StudioUpdateStatus::success && !public_json.empty(); }
};

struct AudioSourcePatch {
    std::optional<bool> muted;
    std::optional<double> volume;
    std::optional<std::string> monitoring;
    std::optional<int> sync_offset_ms;
    std::optional<int> audio_track;
};

class StudioController {
public:
    StudioController(StudioDocument document, std::filesystem::path file, SceneController &program);

    [[nodiscard]] StudioUpdateResult snapshot() const;
    StudioUpdateResult replace(std::string_view candidate_json,
                               std::optional<std::uint64_t> expected_revision);
    StudioUpdateResult take(std::optional<std::uint64_t> expected_revision);
    StudioUpdateResult undo(std::optional<std::uint64_t> expected_revision);
    StudioUpdateResult redo(std::optional<std::uint64_t> expected_revision);
    StudioUpdateResult update_audio(std::string_view scene_id, std::string_view source_id,
                                    const AudioSourcePatch &patch,
                                    std::optional<std::uint64_t> expected_revision);

private:
    StudioUpdateResult restore_history(bool redo, std::optional<std::uint64_t> expected_revision);
    StudioUpdateResult result_locked(StudioUpdateStatus status, std::string error = {}) const;

    mutable std::mutex mutex_;
    StudioDocument document_;
    std::filesystem::path file_;
    SceneController &program_;
    StudioHistory history_;
};

} // namespace webobs
