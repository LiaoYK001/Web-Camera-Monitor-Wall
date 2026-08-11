#pragma once

#include "webobs/scene_document.hpp"

#include <cstddef>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace webobs {

// Owns the libobs sources and scene corresponding to one SceneDocument.
// prepare() is side-effect free for the active program scene; commit_prepared()
// performs the non-failing output swap. Callers can persist between the two.
class ObsSceneRuntime {
public:
    explicit ObsSceneRuntime(int connect_timeout_seconds);
    ~ObsSceneRuntime();

    ObsSceneRuntime(const ObsSceneRuntime &) = delete;
    ObsSceneRuntime &operator=(const ObsSceneRuntime &) = delete;

    std::optional<std::string> prepare(const SceneDocument &document);
    [[nodiscard]] bool has_prepared() const;
    void discard_prepared();
    void commit_prepared();

    void activate();
    void deactivate();

    [[nodiscard]] std::size_t visible_source_count() const;
    [[nodiscard]] std::size_t ready_visible_source_count() const;
    [[nodiscard]] std::vector<std::string> pending_visible_source_ids() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace webobs
