#pragma once

#include <cstddef>
#include <string>
#include <vector>

#include "source_ownership.hpp"
#include "wall_snapshot.hpp"

namespace webobs::native_host {

// Internal/unexposed reversible apply planner. It turns a freshly observed
// wall snapshot, the private provenance ledger and a desired camera state
// (camera ids + source UUIDs, e.g. from a validated offline migration
// candidate) into a deterministic operation plan plus an exact inverse
// rollback journal.
//
// This is a PLAN, not an executor and not an authorization decision: it
// performs no graph mutation, no persistence, no authorization and no I/O.
// Whether the caller may apply this plan must be decided separately (e.g.
// the live-view pipeline or an authorized migration path) against a fresh
// snapshot; pairing a plan with execution across different observations is
// outside this module and the TOCTOU window stays there.
struct WallApplyEntry {
	std::string camera_id;   // exact cluster registry identifier syntax
	std::string source_uuid; // canonical lowercase 8-4-4-4-12 hex UUID
};

enum class WallApplyPlanStatus {
	planned,       // at least one mutation operation; journal is the exact inverse
	noop,          // desired state already matches every bound snapshot entry
	request_invalid, // desired state or snapshot itself violates strict syntax/count/uniqueness
	ledger_invalid,  // ledger violates the fail-closed consistency rules
	graph_unbound,   // a snapshot entry has no exact ledger match; no plan may be built
};

enum class WallApplyOpKind { keep, replace, remove, add };

struct WallApplyOperation {
	WallApplyOpKind kind = WallApplyOpKind::keep;
	std::string camera_id;
	std::string old_uuid; // empty for `add`
	std::string new_uuid; // empty for `remove` and `keep`
};

enum class WallApplyUndoKind { restore_binding, drop_binding };

struct WallApplyUndo {
	WallApplyUndoKind kind = WallApplyUndoKind::restore_binding;
	std::string camera_id;
	std::string uuid;
};

struct WallApplyPlan {
	WallApplyPlanStatus status = WallApplyPlanStatus::request_invalid;
	// Snapshot order for current-side operations, then desired order for adds.
	std::vector<WallApplyOperation> operations;
	// Exact inverse sequence, in the order an executor must replay it.
	std::vector<WallApplyUndo> rollback;
};

// Fail-closed rules (no I/O, statically reviewable):
//  1. desired must contain exactly five entries with valid camera-id/UUID
//     syntax and no duplicate camera id or UUID, else `request_invalid`;
//  2. snapshot UUIDs must be valid and duplicate-free, else `request_invalid`;
//  3. the ledger must pass ownership_ledger_consistent, else `ledger_invalid`;
//  4. every snapshot entry must match a ledger UUID exactly, else
//     `graph_unbound` — an unowned graph is never planned over;
//  5. every desired UUID must not already be bound (in the ledger) to a
//     different camera, else `request_invalid`;
//  6. diff yields keep/replace/remove/add per camera; all keeps yield `noop`.
//
// Rollback restores ledger bindings only (via record_created_source replay or
// leaving stale claims): re-creating a removed OBS source object requires the
// executor's protected settings backup, which this planner never sees. A
// removed or replaced old UUID may stay claimed in the ledger as a stale
// entry; a later conflicting record is fail-closed. No durability, atomicity
// or crash-recovery claim is made for any journal.
WallApplyPlan plan_wall_apply(const WallSnapshot &snapshot, const std::vector<OwnershipEntry> &ledger,
			      const std::vector<WallApplyEntry> &desired) noexcept;
} // namespace webobs::native_host
