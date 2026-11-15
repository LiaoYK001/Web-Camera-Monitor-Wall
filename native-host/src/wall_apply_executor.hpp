#pragma once

#include "source_ownership.hpp"
#include "wall_apply_plan.hpp"
#include "wall_snapshot.hpp"

#include <cstddef>
#include <functional>
#include <string_view>
#include <vector>

namespace webobs::native_host {

// Internal/unexposed execution boundary for a WallApplyPlan. Two phases:
//
//  1. Re-derivation: the plan is rebuilt with plan_wall_apply from a FRESH
//     snapshot and the CURRENT ledger, using the desired state implied by the
//     plan's own operations. The passed plan must be byte-for-byte equal to
//     that re-derived plan (status, operations and rollback journal), else the
//     plan is stale and NOTHING is executed and no target callback runs.
//  2. Execution: replace/remove/add operations run in plan order through the
//     injected target (keep operations never touch it). On the first forward
//     failure the journal of the applied prefix is replayed in reverse order;
//     every undo entry is attempted even after one fails, and the status
//     reports whether the rollback completed.
//
// This is NOT wired to OBS, NOT an authorization check and NOT an execution
// fence: the caller still owns authorization (e.g. authorize_wall_apply), and
// the re-derivation only narrows the observation-to-execution window to the
// duration between the caller's fresh observation and these target calls.
// Rollback restores graph/ledger claims only (it cannot recreate deleted
// source objects or their settings), and no atomicity, durability or
// crash-recovery guarantee is made for any step.
enum class WallApplyExecutionStatus {
	applied,                             // every operation applied; no rollback needed
	noop,                                // plan implied no mutations; zero target calls
	stale_plan,                          // plan no longer matches a fresh snapshot/ledger
	invalid_plan,                        // plan status/operations/journal violate the contract
	operation_failed_rolled_back,        // forward failure, whole prefix undone
	operation_failed_rollback_incomplete,// forward failure, at least one undo failed
};

struct WallApplyExecution {
	WallApplyExecutionStatus status = WallApplyExecutionStatus::invalid_plan;
	std::size_t applied_operations = 0; // mutating operations applied before failure
	std::size_t rolled_back_operations = 0; // forward operations whose undo completed
	std::size_t failed_undo_entries = 0;    // undo entries that failed
};

struct WallApplyTarget {
	// Forward mutation of one planned replace/remove/add operation.
	std::function<bool(WallApplyOpKind, std::string_view camera_id, std::string_view old_uuid,
			   std::string_view new_uuid)>
		apply;
	// Replay of one journal entry (drop the new binding / restore the old one).
	std::function<bool(WallApplyUndoKind, std::string_view camera_id, std::string_view uuid)> undo;
};

[[nodiscard]] WallApplyExecution execute_wall_apply(const WallApplyPlan &plan, const WallSnapshot &fresh,
						    const std::vector<OwnershipEntry> &ledger,
						    const WallApplyTarget &target) noexcept;

} // namespace webobs::native_host
