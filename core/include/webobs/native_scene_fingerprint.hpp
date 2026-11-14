#pragma once
#include "webobs/scene_document.hpp"
#include <optional>
#include <string>

namespace webobs {
// A content precondition, NOT an authorization token. The caller must still
// freshly authorize the session and every camera/Profile before every action.
// Global Studio revision is excluded; actual flattened content and fps are bound.
std::optional<std::string> native_scene_fingerprint(const SceneDocument &document, int fps);
}
