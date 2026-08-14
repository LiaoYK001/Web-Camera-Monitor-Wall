#include "webobs/scene_controller.hpp"

#include "webobs/scene_mutation.hpp"
#include "webobs/scene_store.hpp"

#include <utility>

namespace webobs {
namespace {

SceneUpdateResult update_failure(SceneUpdateStatus status, std::uint64_t revision, std::string error)
{
    SceneUpdateResult result;
    result.status = status;
    result.revision = revision;
    result.error = std::move(error);
    return result;
}

SceneUpdateStatus map_rejection(SceneMutationRejection rejection)
{
    switch (rejection) {
    case SceneMutationRejection::precondition_required:
        return SceneUpdateStatus::precondition_required;
    case SceneMutationRejection::revision_conflict:
        return SceneUpdateStatus::revision_conflict;
    case SceneMutationRejection::invalid_document:
        return SceneUpdateStatus::invalid_document;
    case SceneMutationRejection::none:
        break;
    }
    return SceneUpdateStatus::invalid_document;
}

} // namespace

SceneController::SceneController(SceneDocument document, std::filesystem::path scene_file,
                                 ObsSceneRuntime &runtime)
    : document_(std::move(document)), scene_file_(std::move(scene_file)), runtime_(runtime)
{
}

SceneSnapshot SceneController::snapshot() const
{
    std::lock_guard lock(mutex_);
    const SceneSerializeResult serialized =
        serialize_scene_json(document_, SceneJsonView::public_api, false);
    SceneSnapshot result;
    result.revision = document_.revision;
    if (serialized.ok())
        result.public_json = serialized.json;
    else
        result.error = serialized.error;
    return result;
}

SceneDocument SceneController::private_document_snapshot() const
{
    std::lock_guard lock(mutex_);
    return document_;
}

SourceHealthSnapshot SceneController::source_health_snapshot() const
{
    std::lock_guard lock(mutex_);
    return runtime_.source_health_snapshot();
}

SceneUpdateResult SceneController::replace(std::string_view candidate_json,
                                           std::optional<std::uint64_t> expected_revision)
{
    std::lock_guard lock(mutex_);
    SceneMutationPlan plan = plan_scene_replacement(document_, candidate_json, expected_revision);
    if (!plan.ok())
        return update_failure(map_rejection(plan.rejection), document_.revision, std::move(plan.error));
    if (scene_file_.empty())
        return update_failure(SceneUpdateStatus::persistence_unavailable, document_.revision,
                              "scene updates require a configured scene file");

    if (const auto runtime_error = runtime_.prepare(*plan.document))
        return update_failure(SceneUpdateStatus::runtime_rejected, document_.revision, *runtime_error);
    if (const auto readiness_error = runtime_.wait_prepared_visible_sources()) {
        runtime_.discard_prepared();
        return update_failure(SceneUpdateStatus::runtime_rejected, document_.revision, *readiness_error);
    }
    if (const auto save_error = save_scene_file_atomic(scene_file_, *plan.document)) {
        runtime_.discard_prepared();
        return update_failure(SceneUpdateStatus::persistence_failed, document_.revision, *save_error);
    }

    runtime_.commit_prepared();
    document_ = std::move(*plan.document);
    const SceneSerializeResult serialized =
        serialize_scene_json(document_, SceneJsonView::public_api, false);
    if (!serialized.ok())
        return update_failure(SceneUpdateStatus::runtime_rejected, document_.revision, serialized.error);

    SceneUpdateResult result;
    result.status = SceneUpdateStatus::success;
    result.revision = document_.revision;
    result.public_json = serialized.json;
    return result;
}

} // namespace webobs
