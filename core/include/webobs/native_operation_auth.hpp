#pragma once

#include "webobs/native_control_auth.hpp"

#include <chrono>
#include <cstddef>
#include <functional>
#include <span>
#include <string_view>

namespace webobs {

// One decision-time requirement for a single whole operation: a trusted
// canonical permission name plus one resource, exactly as the backend
// contract defines them. The trusted adapter supplies requirements in the
// intended evaluation order (coarse collection permission first, then every
// affected camera); this orchestrator never reorders or invents them.
struct NativeOperationRequirement {
    std::string_view permission;
    std::string_view resource_id;
};

enum class NativeOperationStatus {
    // Every requirement produced a fresh authoritative allow against the
    // exact bound identity within one operation budget.
    allowed,
    // Some requirement was explicitly denied by the authority. Later
    // requirements were not consulted.
    forbidden,
    // The authoritative account no longer matches the exact bound identity
    // mid-operation (password/enabled rotation, delete/recreate). Stopping is
    // the safe partial decision; the operation must not execute.
    binding_invalid,
    // Transport failure, backend exception or the whole-operation budget
    // exhausted before all requirements were evaluated.
    unavailable,
    // Caller bug: malformed identity, budget or requirement set. No backend
    // call happens.
    invalid_request,
};

struct NativeOperationAuthorization {
    NativeOperationStatus status = NativeOperationStatus::unavailable;
    // Requirements actually evaluated. Equals the total count only on allow.
    std::size_t evaluated = 0;

    [[nodiscard]] bool allowed() const noexcept { return status == NativeOperationStatus::allowed; }
};

// Deterministic clock injection for budget tests; defaults to the real clock.
using NativeOperationClock = std::function<std::chrono::steady_clock::time_point()>;

// Bounded whole-operation authorization for one trusted multi-resource
// command (for example: one coarse scene.write plus live.view on five cameras
// for a wall operation). Each requirement performs its own fresh authoritative
// backend lookup; there is no cached grant and the returned value is NOT a
// reusable authorization token. Fail-closed rules:
//  * the exact bound identity is required up front and is compared by every
//    backend call; a mid-operation rotation/delete surfaces as
//    binding_invalid and stops evaluation instead of stitching stale epochs;
//  * a single total budget covers the whole evaluation; remaining budget <= 0
//    before a call stops with unavailable and skips later requirements;
//  * an explicit deny stops with forbidden immediately;
//  * backend exceptions never leak messages and map to unavailable.
// This is a decision-time gate, not an execution-time fence: callers must
// execute the allowlisted action immediately after allow and revalidate the
// session binding, exactly as NativeControlAuth requires. The per-backend-call
// cap stays whatever the injected adapter enforces (the cluster backend uses
// <=2000ms), so the absolute worst-case wall time of THIS function is the
// total budget plus one backend call; hosts must additionally enforce their
// own transport/command deadline.
[[nodiscard]] NativeOperationAuthorization authorize_operation(
    std::string_view principal, const SessionIdentity &identity,
    std::span<const NativeOperationRequirement> requirements,
    const NativeAuthorizationBackend &backend,
    std::chrono::milliseconds total_budget,
    NativeOperationClock now = [] { return std::chrono::steady_clock::now(); });

} // namespace webobs

/* Unexposed library boundary only. Production wiring still owns transport,
 * session lifetime, the per-command host deadline and interception of every
 * relevant frontend action before an allowed result may trigger an action. */
