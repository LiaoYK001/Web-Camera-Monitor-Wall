#pragma once

#include "source_ownership.hpp"
#include "wall_apply_backup.hpp"
#include "wall_apply_executor.hpp"
#include "wall_apply_plan.hpp"
#include "wall_snapshot.hpp"

#include <cstddef>

namespace webobs::native_host {

// Internal/unexposed composition of the backup capture and the executor: the
// destructive material is captured from the PLAN before any target call, and
// an execution failure that fully undoes its prefix then restores the captured
// settings newest-first. This closes the executor's documented settings gap
// for `replace`/`remove`, but it is still NOT wired to OBS, NOT an
// authorization check and NOT an execution fence: `replace`/`remove` hand the
// old object to the target, whose undo is responsible for recreating it so the
// writer can apply the captured material.
//
// Boundaries: the capture reads through the injected reader only; nothing is
// persisted, signed or encrypted here, and no atomicity, durability or
// crash-recovery guarantee is made. A partially failed rollback deliberately
// performs no settings restore (the target state is unknown); settings are only
// written when the whole forward prefix was undone.
enum class WallApplyBackupExecutionStatus {
	applied,                  // every operation applied; no rollback needed
	noop,                     // plan implied no mutations; zero target calls
	backup_unavailable,       // destructive material could not be captured
	stale_plan,               // plan no longer matches a fresh snapshot/ledger
	invalid_plan,             // plan status/operations/journal violate the contract
	rolled_back,              // forward failure, whole prefix undone, material restored
	rollback_incomplete,      // forward failure, at least one undo failed
	rollback_settings_incomplete, // prefix undone but a captured material restore failed
};

struct WallApplyBackupExecution {
	WallApplyBackupExecutionStatus status = WallApplyBackupExecutionStatus::invalid_plan;
	WallApplyExecution execution;   // forward/undo counts from the executor
	WallApplyRestore restore;       // settings restore counts (zero unless attempted)
	std::size_t captured_entries = 0;
};

// Order: validate the plan shape, capture material, then execute. A plan that
// is stale for the fresh observation is rejected by the executor after the
// capture, so no target callback ever runs on a stale plan.
[[nodiscard]] WallApplyBackupExecution execute_wall_apply_with_backup(
	const WallApplyPlan &plan, const WallSnapshot &fresh, const std::vector<OwnershipEntry> &ledger,
	const WallApplyTarget &target, const WallApplyBackupReader &reader,
	const WallApplyBackupWriter &writer) noexcept;

} // namespace webobs::native_host
