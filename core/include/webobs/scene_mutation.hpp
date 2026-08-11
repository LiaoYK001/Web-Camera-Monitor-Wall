#pragma once

#include "webobs/scene_document.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace webobs {

enum class SceneMutationRejection {
    none,
    precondition_required,
    revision_conflict,
    invalid_document,
};

struct SceneMutationPlan {
    std::optional<SceneDocument> document;
    SceneMutationRejection rejection = SceneMutationRejection::none;
    std::string error;

    [[nodiscard]] bool ok() const
    {
        return document.has_value() && rejection == SceneMutationRejection::none && error.empty();
    }
};

SceneMutationPlan plan_scene_replacement(const SceneDocument &current, std::string_view candidate_json,
                                         std::optional<std::uint64_t> expected_revision);

} // namespace webobs
