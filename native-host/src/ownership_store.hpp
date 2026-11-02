#pragma once

#include <string>
#include <vector>

#include "source_ownership.hpp"

namespace webobs::native_host {

// Caller-owned persistence for the provenance ledger behind one private file
// path. This performs real file IO only; it does NOT claim fsync/rename power
// failure atomicity or protection strength: on Windows an existing target is
// removed before the rename, so a crash between those steps can lose the
// previous ledger. The stored content is a claim record, not a secret and not
// an authorization grant; pairing with a fresh snapshot at decision time is
// still required.
enum class OwnershipStoreStatus { success, absent, invalid_ledger, io_error };

struct OwnershipStoreResult {
	OwnershipStoreStatus status = OwnershipStoreStatus::io_error;
	// Populated on success; `absent` yields a valid empty ledger view.
	std::vector<OwnershipEntry> entries;
};

// Reads at most 16 KiB; a missing file is `absent`, corrupt or oversized
// content is `invalid_ledger` and never repaired here.
OwnershipStoreResult load_ownership_store(const std::string &path) noexcept;

// Encodes and replaces the file atomically where the platform rename replaces
// atomically. An inconsistent ledger is refused (`invalid_ledger`) before any
// write, so existing content survives.
OwnershipStoreStatus save_ownership_store(const std::string &path,
					  const std::vector<OwnershipEntry> &entries) noexcept;
} // namespace webobs::native_host
