#include "webobs/studio_controller.hpp"

#include "webobs/redaction.hpp"
#include "webobs/studio_store.hpp"

#include <algorithm>
#include <limits>
#include <utility>

namespace webobs {
namespace {

bool redacted_rtsp(std::string_view url)
{
    const std::size_t scheme = url.find("://");
    if (scheme == std::string_view::npos)
        return false;
    const std::size_t start = scheme + 3;
    const std::size_t end = url.find_first_of("/?#", start);
    const std::string_view authority = url.substr(start, end - start);
    const std::size_t at = authority.rfind('@');
    if (at == std::string_view::npos)
        return false;
    const std::string_view userinfo = authority.substr(0, at);
    return userinfo == "***" || userinfo == "***:***";
}

bool redacted_browser(std::string_view url)
{
    return url.find("?***") != std::string_view::npos || url.find("#***") != std::string_view::npos;
}

std::optional<std::string> restore_secrets(const StudioDocument &current, StudioDocument &candidate)
{
    for (SceneDocument &candidate_scene : candidate.scenes) {
        const auto scene = std::find_if(current.scenes.begin(), current.scenes.end(),
                                        [&candidate_scene](const SceneDocument &entry) {
                                            return entry.id == candidate_scene.id;
                                        });
        for (SceneSource &candidate_source : candidate_scene.sources) {
            const SceneSource *existing = nullptr;
            if (scene != current.scenes.end()) {
                const auto found = std::find_if(scene->sources.begin(), scene->sources.end(),
                                                [&candidate_source](const SceneSource &entry) {
                                                    return entry.id == candidate_source.id;
                                                });
                if (found != scene->sources.end())
                    existing = &*found;
            }
            if (candidate_source.kind == "rtsp") {
                if (existing && existing->kind == "rtsp" &&
                    candidate_source.rtsp_url == redact_rtsp_credentials(existing->rtsp_url)) {
                    candidate_source.rtsp_url = existing->rtsp_url;
                } else if (redacted_rtsp(candidate_source.rtsp_url)) {
                    return "redacted RTSP credentials are valid only for an unchanged existing Studio source";
                }
            } else if (candidate_source.kind == "browser") {
                if (existing && existing->kind == "browser" &&
                    candidate_source.browser_url == redact_browser_url(existing->browser_url)) {
                    candidate_source.browser_url = existing->browser_url;
                } else if (redacted_browser(candidate_source.browser_url)) {
                    return "redacted browser secrets are valid only for an unchanged existing Studio source";
                }
            }
        }
    }
    return std::nullopt;
}

StudioDocument bootstrap_history_document(const StudioDocument &candidate, std::uint64_t revision)
{
    StudioDocument result = candidate;
    result.revision = revision;
    return result;
}

} // namespace

StudioController::StudioController(StudioDocument document, std::filesystem::path file,
                                   SceneController &program)
    : document_(std::move(document)), file_(std::move(file)), program_(program)
{
}

StudioUpdateResult StudioController::result_locked(StudioUpdateStatus status, std::string error) const
{
    StudioUpdateResult result;
    result.status = status;
    result.revision = document_.revision;
    result.error = std::move(error);
    if (status == StudioUpdateStatus::success) {
        const SceneSerializeResult encoded =
            serialize_studio_json(document_, SceneJsonView::public_api, false);
        if (encoded.ok())
            result.public_json = encoded.json;
        else {
            result.status = StudioUpdateStatus::invalid_document;
            result.error = encoded.error;
        }
    }
    return result;
}

StudioUpdateResult StudioController::snapshot() const
{
    std::lock_guard lock(mutex_);
    return result_locked(StudioUpdateStatus::success);
}

StudioUpdateResult StudioController::replace(std::string_view candidate_json,
                                             std::optional<std::uint64_t> expected_revision)
{
    std::lock_guard lock(mutex_);
    if (!expected_revision)
        return result_locked(StudioUpdateStatus::precondition_required, "If-Match revision is required");
    if (*expected_revision != document_.revision)
        return result_locked(StudioUpdateStatus::revision_conflict,
                             "Studio revision does not match If-Match");
    if (document_.revision >= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
        return result_locked(StudioUpdateStatus::revision_conflict, "Studio revision cannot be advanced");
    StudioParseResult parsed = parse_studio_json(candidate_json);
    if (!parsed.ok())
        return result_locked(StudioUpdateStatus::invalid_document, std::move(parsed.error));
    StudioDocument candidate = std::move(*parsed.document);
    if (candidate.revision != document_.revision)
        return result_locked(StudioUpdateStatus::revision_conflict,
                             "Studio document revision does not match If-Match");
    if (const auto secret_error = restore_secrets(document_, candidate))
        return result_locked(StudioUpdateStatus::invalid_document, *secret_error);
    candidate.revision = document_.revision + 1;
    if (const auto validation_error = validate_studio_document(candidate))
        return result_locked(StudioUpdateStatus::invalid_document, *validation_error);
    const SceneSerializeResult previous =
        serialize_studio_json(document_, SceneJsonView::persistence, false);
    if (!previous.ok())
        return result_locked(StudioUpdateStatus::persistence_failed, previous.error);
    if (const auto save_error = save_studio_file_atomic(file_, candidate))
        return result_locked(StudioUpdateStatus::persistence_failed, *save_error);
    history_.push(previous.json);
    document_ = std::move(candidate);
    return result_locked(StudioUpdateStatus::success);
}

StudioUpdateResult StudioController::take(std::optional<std::uint64_t> expected_revision)
{
    std::lock_guard lock(mutex_);
    if (!expected_revision)
        return result_locked(StudioUpdateStatus::precondition_required, "If-Match revision is required");
    if (*expected_revision != document_.revision)
        return result_locked(StudioUpdateStatus::revision_conflict,
                             "Studio revision does not match If-Match");
    if (document_.revision >= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
        return result_locked(StudioUpdateStatus::revision_conflict, "Studio revision cannot be advanced");

    StudioFlattenResult flattened = flatten_studio_scene(document_, document_.preview_scene_id);
    if (!flattened.ok())
        return result_locked(StudioUpdateStatus::invalid_document, std::move(flattened.error));
    const SceneDocument previous_program = program_.private_document_snapshot();
    flattened.document->revision = previous_program.revision;
    const SceneSerializeResult candidate_json =
        serialize_scene_json(*flattened.document, SceneJsonView::persistence, false);
    if (!candidate_json.ok())
        return result_locked(StudioUpdateStatus::invalid_document, candidate_json.error);

    const SceneUpdateResult applied =
        program_.replace(candidate_json.json, previous_program.revision, document_.transition.kind,
                         document_.transition.duration_ms);
    if (!applied.ok())
        return result_locked(StudioUpdateStatus::runtime_rejected, applied.error);

    const SceneSerializeResult previous_studio =
        serialize_studio_json(document_, SceneJsonView::persistence, false);
    StudioDocument updated = document_;
    updated.program_scene_id = updated.preview_scene_id;
    ++updated.revision;
    if (const auto save_error = save_studio_file_atomic(file_, updated)) {
        SceneDocument rollback = previous_program;
        rollback.revision = applied.revision;
        const SceneSerializeResult rollback_json =
            serialize_scene_json(rollback, SceneJsonView::persistence, false);
        if (rollback_json.ok())
            (void)program_.replace(rollback_json.json, applied.revision, "cut", 0);
        return result_locked(StudioUpdateStatus::persistence_failed,
                             "Studio Take was rolled back because persistence failed: " + *save_error);
    }
    if (previous_studio.ok())
        history_.push(previous_studio.json);
    document_ = std::move(updated);
    return result_locked(StudioUpdateStatus::success);
}

StudioUpdateResult StudioController::restore_history(bool redo_action,
                                                     std::optional<std::uint64_t> expected_revision)
{
    std::lock_guard lock(mutex_);
    if (!expected_revision)
        return result_locked(StudioUpdateStatus::precondition_required, "If-Match revision is required");
    if (*expected_revision != document_.revision)
        return result_locked(StudioUpdateStatus::revision_conflict,
                             "Studio revision does not match If-Match");
    if (document_.revision >= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
        return result_locked(StudioUpdateStatus::revision_conflict, "Studio revision cannot be advanced");
    const SceneSerializeResult current =
        serialize_studio_json(document_, SceneJsonView::persistence, false);
    if (!current.ok())
        return result_locked(StudioUpdateStatus::persistence_failed, current.error);
    StudioHistory candidate_history = history_;
    const std::optional<std::string> state =
        redo_action ? candidate_history.redo(current.json) : candidate_history.undo(current.json);
    if (!state)
        return result_locked(StudioUpdateStatus::history_empty, "Studio history is empty");
    StudioParseResult parsed = parse_studio_json(*state);
    if (!parsed.ok())
        return result_locked(StudioUpdateStatus::invalid_document, parsed.error);
    StudioDocument restored = bootstrap_history_document(*parsed.document, document_.revision + 1);
    StudioFlattenResult flattened = flatten_studio_scene(restored, restored.program_scene_id);
    if (!flattened.ok())
        return result_locked(StudioUpdateStatus::invalid_document, flattened.error);
    const SceneDocument previous_program = program_.private_document_snapshot();
    flattened.document->revision = previous_program.revision;
    const SceneSerializeResult candidate_json =
        serialize_scene_json(*flattened.document, SceneJsonView::persistence, false);
    if (!candidate_json.ok())
        return result_locked(StudioUpdateStatus::invalid_document, candidate_json.error);
    const SceneUpdateResult applied =
        program_.replace(candidate_json.json, previous_program.revision, "cut", 0);
    if (!applied.ok())
        return result_locked(StudioUpdateStatus::runtime_rejected, applied.error);
    if (const auto save_error = save_studio_file_atomic(file_, restored)) {
        SceneDocument rollback = previous_program;
        rollback.revision = applied.revision;
        const SceneSerializeResult rollback_json =
            serialize_scene_json(rollback, SceneJsonView::persistence, false);
        if (rollback_json.ok())
            (void)program_.replace(rollback_json.json, applied.revision, "cut", 0);
        return result_locked(StudioUpdateStatus::persistence_failed,
                             "Studio history restore was rolled back because persistence failed: " +
                                 *save_error);
    }
    document_ = std::move(restored);
    history_ = std::move(candidate_history);
    return result_locked(StudioUpdateStatus::success);
}

StudioUpdateResult StudioController::undo(std::optional<std::uint64_t> expected_revision)
{
    return restore_history(false, expected_revision);
}

StudioUpdateResult StudioController::redo(std::optional<std::uint64_t> expected_revision)
{
    return restore_history(true, expected_revision);
}

StudioUpdateResult StudioController::update_audio(std::string_view scene_id, std::string_view source_id,
                                                  const AudioSourcePatch &patch,
                                                  std::optional<std::uint64_t> expected_revision)
{
    std::lock_guard lock(mutex_);
    if (!expected_revision)
        return result_locked(StudioUpdateStatus::precondition_required, "If-Match revision is required");
    if (*expected_revision != document_.revision)
        return result_locked(StudioUpdateStatus::revision_conflict,
                             "Studio revision does not match If-Match");
    if (document_.revision >= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
        return result_locked(StudioUpdateStatus::revision_conflict, "Studio revision cannot be advanced");
    StudioDocument candidate = document_;
    const auto scene = std::find_if(candidate.scenes.begin(), candidate.scenes.end(),
                                    [scene_id](const SceneDocument &value) { return value.id == scene_id; });
    if (scene == candidate.scenes.end())
        return result_locked(StudioUpdateStatus::invalid_document, "audio Scene was not found");
    const auto source = std::find_if(scene->sources.begin(), scene->sources.end(),
                                     [source_id](const SceneSource &value) { return value.id == source_id; });
    if (source == scene->sources.end())
        return result_locked(StudioUpdateStatus::invalid_document, "audio source was not found");
    if (patch.muted) source->muted = *patch.muted;
    if (patch.volume) source->volume = *patch.volume;
    if (patch.monitoring) source->monitoring = *patch.monitoring;
    if (patch.sync_offset_ms) source->sync_offset_ms = *patch.sync_offset_ms;
    if (patch.audio_track) source->audio_track = *patch.audio_track;
    ++candidate.revision;
    if (const auto validation_error = validate_studio_document(candidate))
        return result_locked(StudioUpdateStatus::invalid_document, *validation_error);
    const SceneSerializeResult previous =
        serialize_studio_json(document_, SceneJsonView::persistence, false);
    if (!previous.ok())
        return result_locked(StudioUpdateStatus::persistence_failed, previous.error);

    const bool program_changed = scene_id == document_.program_scene_id;
    SceneDocument previous_program;
    std::uint64_t applied_revision = 0;
    if (program_changed) {
        StudioFlattenResult flattened = flatten_studio_scene(candidate, candidate.program_scene_id);
        if (!flattened.ok())
            return result_locked(StudioUpdateStatus::invalid_document, flattened.error);
        previous_program = program_.private_document_snapshot();
        flattened.document->revision = previous_program.revision;
        const SceneSerializeResult encoded =
            serialize_scene_json(*flattened.document, SceneJsonView::persistence, false);
        if (!encoded.ok())
            return result_locked(StudioUpdateStatus::invalid_document, encoded.error);
        const SceneUpdateResult applied = program_.replace(encoded.json, previous_program.revision, "cut", 0);
        if (!applied.ok())
            return result_locked(StudioUpdateStatus::runtime_rejected, applied.error);
        applied_revision = applied.revision;
    }
    if (const auto save_error = save_studio_file_atomic(file_, candidate)) {
        if (program_changed) {
            previous_program.revision = applied_revision;
            const SceneSerializeResult rollback =
                serialize_scene_json(previous_program, SceneJsonView::persistence, false);
            if (rollback.ok())
                (void)program_.replace(rollback.json, applied_revision, "cut", 0);
        }
        return result_locked(StudioUpdateStatus::persistence_failed, *save_error);
    }
    history_.push(previous.json);
    document_ = std::move(candidate);
    return result_locked(StudioUpdateStatus::success);
}

} // namespace webobs
