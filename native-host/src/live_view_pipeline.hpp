#pragma once

#include "source_ownership.hpp"
#include "wall_live_decision.hpp"
#include "wall_snapshot.hpp"
#include "webobs/authentication.hpp"
#include "webobs/native_control_auth.hpp"
#include "webobs/native_operation_auth.hpp"

#include <chrono>
#include <cstddef>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs::native_host {

// Internal/unexposed composition of the existing fail-closed boundaries into one
// decision-time live-view pipeline: exact bound session first (legacy unbound
// sessions yield `unauthenticated` with zero graph observation and zero backend
// calls), then a FRESH graph snapshot via the injected provider (failure yields
// `unavailable` before any backend call), then ledger × snapshot pairing, then
// per-camera `live.view` authorization through authorize_operation with the
// remaining whole-operation budget.
//
// This is a decision-time pipeline, NOT an execution fence, a grant or a
// reusable capability. It does not prove media liveness, graph stability,
// policy-epoch consistency across calls, or that any later action rechecks
// these inputs; the TOCTOU window between snapshot observation and the action
// stays outside this module. The provider and backend callbacks must be the
// trusted adapters supplied by the host, never caller-controlled identity or
// cached permission results.
enum class LiveViewPipelineStatus {
	allowed,
	forbidden,           // authoritative denial of one bound camera
	graph_unbound,       // a snapshot entry has no exact ledger match; zero backend calls
	ledger_invalid,      // ledger violates the shared fail-closed rules; zero backend calls
	unauthenticated,     // missing/expired session, legacy unbound session, or mid-pipeline identity loss
	unavailable,         // provider failure, backend indeterminate state, or budget exhausted
	invalid_request,     // caller bug: bad token, budget, or snapshot violating strict syntax
};

struct LiveViewPipelineAuthorization {
	LiveViewPipelineStatus status = LiveViewPipelineStatus::unavailable;
	// Bound camera ids in snapshot order, present only on `allowed`.
	std::vector<std::string> camera_ids;
	// Timely authorized camera decisions, only meaningful on `allowed`.
	std::size_t evaluated = 0;
};

// Trusted fresh-observation seam: each call must re-enumerate the live scene
// graph and return exactly five entries, or nullopt when observation failed.
// Thrown exceptions collapse to `unavailable` without relaying content.
using WallSnapshotProvider = std::function<std::optional<WallSnapshot>()>;

LiveViewPipelineAuthorization authorize_live_view(
	SessionStore &sessions,
	std::string_view session_token,
	const std::vector<OwnershipEntry> &ledger,
	const WallSnapshotProvider &provider,
	const NativeAuthorizationBackend &backend,
	std::chrono::milliseconds total_budget,
	NativeOperationClock now = [] { return std::chrono::steady_clock::now(); }) noexcept;

} // namespace webobs::native_host

/* Unexposed pipeline boundary only. Production wiring still owns session
 * creation/login, the trusted snapshot observer against real OBS, the cluster
 * backend transport, per-action host deadlines and interception of every
 * relevant frontend action before an allowed result may trigger an action. */