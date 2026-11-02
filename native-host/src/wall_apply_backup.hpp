#pragma once

#include "wall_apply_plan.hpp"

#include <cstddef>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs::native_host {

// Bounded backup material captured BEFORE execution for every operation that
// destroys or replaces an existing source object (`replace`/`remove`). The
// material is the source's private opaque settings blob, supplied by an
// injected reader; this module never reads OBS, files, the registry or the
// network itself. The backup is evidence for a later best-effort restore, not
// a durability, atomicity or authorization guarantee.
struct WallApplySourceBackup {
	std::string camera_id;
	std::string uuid; // the old source UUID being destroyed
	std::vector<unsigned char> settings;
};

enum class WallApplyBackupStatus {
	captured,        // every destructive operation has bounded material
	noop,            // the plan destroys nothing; no reader calls were made
	request_invalid, // plan status/operations violate the apply-plan contract
	unavailable,     // reader failed, returned nothing, or the material was unusable
};

struct WallApplyBackup {
	WallApplyBackupStatus status = WallApplyBackupStatus::request_invalid;
	// Plan order. Empty unless `captured`.
	std::vector<WallApplySourceBackup> entries;
};

// Returns the bounded opaque settings of the source with this UUID, or nothing
// if the source no longer exists / cannot be read.
using WallApplyBackupReader = std::function<std::optional<std::vector<unsigned char>>(std::string_view uuid)>;
// Restores one captured blob onto the recreated source with this UUID.
using WallApplyBackupWriter = std::function<bool(std::string_view uuid, const std::vector<unsigned char> &settings)>;

constexpr std::size_t kMaxWallApplySettingsBytes = 65536;
constexpr std::size_t kMaxWallApplyBackupBytes = 524288;

// Fail-closed rules (no I/O): only `planned`/`noop` plans are accepted; every
// replace/remove operation must have a valid old UUID; the reader is consulted
// exactly once per destructive operation in plan order; a nullopt result, a
// thrown exception or material larger than kMaxWallApplySettingsBytes makes
// the whole capture `unavailable` (the executor must not run on a partial
// backup). Duplicate destructive UUIDs make the plan `request_invalid`
// because one blob must map to exactly one source identity.
[[nodiscard]] WallApplyBackup capture_wall_apply_backup(const WallApplyPlan &plan,
						       const WallApplyBackupReader &reader) noexcept;

struct WallApplyRestore {
	bool complete = false;
	std::size_t restored = 0;
	std::size_t failed = 0;
};

// Best effort, newest first: every entry is attempted even after a failure,
// and the counts report what actually happened. Restoring is only meaningful
// after a failed execution recreated the affected source objects.
[[nodiscard]] WallApplyRestore restore_wall_apply_backup(const WallApplyBackup &backup,
							const WallApplyBackupWriter &writer) noexcept;

} // namespace webobs::native_host
