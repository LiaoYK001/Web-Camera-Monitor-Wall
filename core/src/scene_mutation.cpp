#include "webobs/scene_mutation.hpp"

#include "webobs/redaction.hpp"

#include <algorithm>
#include <limits>
#include <string>
#include <string_view>
#include <utility>

namespace webobs {
namespace {

SceneMutationPlan reject(SceneMutationRejection rejection, std::string message)
{
    SceneMutationPlan result;
    result.rejection = rejection;
    result.error = std::move(message);
    return result;
}

bool contains_redacted_userinfo(std::string_view url)
{
    const std::size_t scheme_end = url.find("://");
    if (scheme_end == std::string_view::npos)
        return false;
    const std::size_t authority_start = scheme_end + 3;
    const std::size_t authority_end = url.find_first_of("/?#", authority_start);
    const std::string_view authority = url.substr(authority_start, authority_end - authority_start);
    const std::size_t at = authority.rfind('@');
    if (at == std::string_view::npos)
        return false;
    const std::string_view userinfo = authority.substr(0, at);
    return userinfo == "***" || userinfo == "***:***";
}

} // namespace

SceneMutationPlan plan_scene_replacement(const SceneDocument &current, std::string_view candidate_json,
                                         std::optional<std::uint64_t> expected_revision)
{
    if (!expected_revision)
        return reject(SceneMutationRejection::precondition_required, "If-Match revision is required");
    if (*expected_revision != current.revision)
        return reject(SceneMutationRejection::revision_conflict, "scene revision does not match If-Match");
    if (current.revision >= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
        return reject(SceneMutationRejection::revision_conflict, "scene revision cannot be advanced");

    SceneParseResult parsed = parse_scene_json(candidate_json);
    if (!parsed.ok())
        return reject(SceneMutationRejection::invalid_document, std::move(parsed.error));
    SceneDocument candidate = std::move(*parsed.document);
    if (candidate.revision != *expected_revision)
        return reject(SceneMutationRejection::revision_conflict,
                      "scene document revision does not match If-Match");

    for (SceneSource &candidate_source : candidate.sources) {
        const auto existing = std::find_if(current.sources.begin(), current.sources.end(),
                                           [&candidate_source](const SceneSource &source) {
                                               return source.id == candidate_source.id;
                                           });
        if (existing != current.sources.end() &&
            candidate_source.rtsp_url == redact_rtsp_credentials(existing->rtsp_url)) {
            candidate_source.rtsp_url = existing->rtsp_url;
        } else if (contains_redacted_userinfo(candidate_source.rtsp_url)) {
            return reject(SceneMutationRejection::invalid_document,
                          "redacted RTSP credentials are valid only for an unchanged existing source");
        }
    }

    candidate.revision = current.revision + 1;
    if (const auto validation_error = validate_scene_document(candidate))
        return reject(SceneMutationRejection::invalid_document, *validation_error);

    SceneMutationPlan result;
    result.document = std::move(candidate);
    return result;
}

} // namespace webobs
