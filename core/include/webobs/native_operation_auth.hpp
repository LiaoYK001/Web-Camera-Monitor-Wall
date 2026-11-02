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
    // Timely allowed prefix, not number of backend calls. A late or rejected
    // reply is not counted. Equals the total count only on allow.
    std::size_t evaluated = 0;

    [[nodiscard]] bool allowed() const noexcept { return status == NativeOperationStatus::allowed; }
};

// Deterministic clock injection for budget tests; defaults to the real clock.
using NativeOperationClock = std::function<std::chrono::steady_clock::time_point()>;

// Sequential decision-time checks for one trusted multi-resource command.
// Each requirement performs a fresh backend lookup; no grant is cached here.
// The result is NOT a reusable authorization token. Fail-closed rules:
//  * require a valid bound identity up front; the authoritative adapter must
//    compare it on every call. Observed identity loss stops evaluation;
//  * check one elapsed-time budget before AND after each synchronous call;
//    elapsed >= budget, a regressing clock or a clock exception yields
//    unavailable, taking precedence even over a late deny/unknown_user;
//  * only timely allowed replies contribute to evaluated; a timely deny stops
//    with forbidden, and backend exceptions map to unavailable without text;
//  * budgets exceeding the steady clock's representable milliseconds are
//    invalid_request; an unrepresentable elapsed interval is unavailable.
// This function neither reads/revokes local sessions nor detects logout.
// authEpoch guards authentication identity, NOT RBAC policy/registry revision:
// fresh sequential decisions need not share a single policy snapshot.
// Synchronous backend/clock callbacks cannot be preempted. Rejection of a late
// reply does not bound actual return time; the host must enforce transport and
// execution deadlines, session revalidation, policy/graph consistency and
// action serialization. No immediate action after allow closes those gaps.
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
