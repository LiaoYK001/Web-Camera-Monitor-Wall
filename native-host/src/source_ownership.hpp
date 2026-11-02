#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace webobs::native_host {

// Internal/unexposed provenance foundation for camera identities.
//
// An entry records ONLY a source created by this native host's own bootstrap:
// camera_id was supplied by the private product config at creation time and
// source_uuid was read from the newly created obs_source. Reusing an existing
// same-named/same-settings source is NOT provenance and never yields an entry;
// names, URLs and settings are deliberately absent so they can never be used
// to adopt an identity (ABA). The ledger is a local claim record, not an
// authorization grant: it does not bind a session, account or RBAC scope, and
// it cannot prove that a later snapshot entry still refers to live media.
struct OwnershipEntry {
	std::string camera_id;    // exact cluster registry identifier syntax (1..64, alnum first)
	std::string source_uuid;  // canonical lowercase 8-4-4-4-12 hex UUID, unnormalized
	std::uint64_t generation; // creation counter within this ledger; strictly increasing
};

inline bool operator==(const OwnershipEntry &a, const OwnershipEntry &b)
{
	return a.camera_id == b.camera_id && a.source_uuid == b.source_uuid && a.generation == b.generation;
}

enum class OwnershipStatus { success, ledger_invalid, record_conflict };

struct OwnershipLedgerResult {
	OwnershipStatus status = OwnershipStatus::ledger_invalid;
	// Present only on success; failures expose no partial entries.
	std::optional<std::vector<OwnershipEntry>> entries;
};

// JSON (schema version 1) for the private durable ledger. The caller owns
// persistence via its own protected-file path; encoding here is deterministic
// and byte-stable. No fsync/rename/crash-atomicity semantics are claimed.
std::string encode_ownership_ledger(const std::vector<OwnershipEntry> &entries);
OwnershipLedgerResult decode_ownership_ledger(std::string_view json) noexcept;

// Records creation provenance for one newly created source. A reused source is
// skipped entirely (the caller simply does not record it). Recording the same
// camera_id again replaces that camera's incarnation and frees its previous
// uuid; any uuid already claimed by another camera — or syntax failure — is a
// record_conflict and leaves `entries` unchanged. A base ledger that is not
// self-consistent yields ledger_invalid.
OwnershipStatus record_created_source(std::vector<OwnershipEntry> &entries, std::string_view camera_id,
				      std::string_view source_uuid) noexcept;

// Result of classifying one snapshot entry against the ledger.
struct OwnershipBinding {
	std::optional<std::string> camera_id; // present only on an exact ledger UUID match
};

// Classifies snapshot entries by exact source_uuid equality. Entries absent
// from the ledger are unbound; an inconsistent ledger (duplicate UUIDs,
// duplicate camera_ids, duplicate generations, bad syntax) fails closed with
// every entry unbound. Classification performs no I/O and no revalidation: an
// ledger entry is not proof that the source still exists, is media-backed or
// was never deleted/recreated; pair it with a fresh snapshot at decision time.
std::vector<OwnershipBinding> classify_wall_entries(const std::vector<OwnershipEntry> &ledger,
						    const std::vector<std::string> &snapshot_uuids) noexcept;
} // namespace webobs::native_host
