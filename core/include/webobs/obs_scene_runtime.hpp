#pragma once

#include "webobs/browser_security.hpp"
#include "webobs/scene_document.hpp"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs {

struct SourceHealthEntry {
    std::string id;
    std::string kind;
    std::string state;
    bool visible = false;
    std::int64_t last_frame_age_ms = -1;
    std::uint64_t restart_count = 0;
};

struct SourceHealthSnapshot {
    std::vector<SourceHealthEntry> sources;
    std::size_t visible = 0;
    std::size_t healthy = 0;
    std::size_t unhealthy = 0;
    std::uint64_t total_restarts = 0;
};

// Owns the libobs sources and scene corresponding to one SceneDocument.
// prepare() is side-effect free for the active program scene; commit_prepared()
// performs the non-failing output swap. Callers can persist between the two.
class ObsSceneRuntime {
public:
    ObsSceneRuntime(int connect_timeout_seconds, BrowserSecurityPolicy browser_security,
                    int source_stale_seconds, int source_recovery_base_seconds,
                    int source_recovery_max_seconds, bool hardware_decode_enabled,
                    bool runtime_enabled = true);
    ~ObsSceneRuntime();

    ObsSceneRuntime(const ObsSceneRuntime &) = delete;
    ObsSceneRuntime &operator=(const ObsSceneRuntime &) = delete;

    std::optional<std::string> prepare(const SceneDocument &document);
    [[nodiscard]] bool has_prepared() const;
    [[nodiscard]] std::optional<std::string> wait_prepared_visible_sources();
    void discard_prepared();
    void commit_prepared();
    void commit_prepared(std::string_view transition_kind, int duration_ms);

    void activate();
    void deactivate();

    [[nodiscard]] std::size_t visible_source_count() const;
    [[nodiscard]] std::size_t ready_visible_source_count() const;
    [[nodiscard]] std::vector<std::string> pending_visible_source_ids() const;
    void maintain_source_health();
    [[nodiscard]] SourceHealthSnapshot source_health_snapshot() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace webobs
