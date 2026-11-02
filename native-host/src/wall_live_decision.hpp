#pragma once

#include <cstddef>
#include <functional>
#include <string>
#include <string_view>
#include <vector>

#include "source_ownership.hpp"
#include "wall_snapshot.hpp"

namespace webobs::native_host {

// Internal/unexposed decision-time pairing: a freshly observed wall snapshot is
// bound against the private provenance ledger and every bound camera must
// receive a permission verdict before `allowed` may be returned.
//
// This is a decision-time snapshot, NOT an authorization grant, a reusable
// capability or an execution fence: nothing here proves the media stays live,
// the graph stays unchanged, or that a later operation re-checks these inputs.
// Callers must pair the ledger with a fresh snapshot AT DECISION TIME; the
// TOCTOU window between snapshot observation and any action remains outside
// this module.
enum class WallLiveDecisionStatus {
	allowed,
	forbidden,       // one camera denied; the accepted prefix is recorded
	graph_unbound,   // a snapshot entry has no exact ledger match; authorizer never called
	ledger_invalid,  // ledger violates the fail-closed rules; authorizer never called
	unavailable,     // authorizer reported an indeterminate state or threw; decision stops
	invalid_request, // snapshot itself violates strict syntax or has duplicate UUIDs
};

enum class CameraPermission { allowed, denied, unavailable };

using WallLiveAuthorizer = std::function<CameraPermission(std::string_view camera_id)>;

struct WallLiveDecision {
	WallLiveDecisionStatus status = WallLiveDecisionStatus::invalid_request;
	// Bound camera ids in snapshot order, present only on `allowed`; empty otherwise.
	std::vector<std::string> bound_camera_ids;
	// Verdicts accepted before any stop; an allow arriving after a stop is ignored.
	std::size_t evaluated = 0;
};

// Fail-closed rules (no I/O, statically reviewable):
//  1. every snapshot UUID must be valid syntax and duplicate-free, else
//     `invalid_request` with zero authorizer calls;
//  2. the ledger must pass ownership_ledger_consistent, else `ledger_invalid`
//     with zero calls;
//  3. every snapshot entry must match a ledger UUID exactly, else
//     `graph_unbound` with zero calls;
//  4. only then the authorizer runs in snapshot order: the first `denied`
//     yields `forbidden` and the first `unavailable` (or thrown exception)
//     yields `unavailable`, both stopping immediately;
//  5. all allowed yields `allowed` with ids in snapshot order.
WallLiveDecision decide_wall_live_view(const WallSnapshot &snapshot,
				       const std::vector<OwnershipEntry> &ledger,
				       const WallLiveAuthorizer &authorizer) noexcept;
} // namespace webobs::native_host
