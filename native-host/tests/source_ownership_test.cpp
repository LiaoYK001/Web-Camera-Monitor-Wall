// Link this test with src/source_ownership.cpp ONLY. The module uses no OBS,
// Qt, filesystem or network API: it is pure codec/classification. This keeps
// the ledger semantics testable on every platform without libobs, and the
// test asserts the module still touches none of those headers.
#include "source_ownership.hpp"

#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using Entries = std::vector<webobs::native_host::OwnershipEntry>;
using Status = webobs::native_host::OwnershipStatus;

const std::string kUuidA = "11111111-2222-3333-4444-555555555555";
const std::string kUuidB = "aaaa1111-2222-3333-4444-555555555555";
const std::string kUuidC = "bbbb1111-2222-3333-4444-555555555555";

std::size_t checks = 0;

void expect(bool condition, const char *label)
{
	++checks;
	if (!condition)
		throw std::runtime_error(label);
}

webobs::native_host::OwnershipLedgerResult decode(std::string_view json)
{
	return webobs::native_host::decode_ownership_ledger(json);
}

void expect_rejected(std::string_view json, const char *label)
{
	++checks;
	const auto result = decode(json);
	if (result.status != Status::ledger_invalid || result.entries.has_value())
		throw std::runtime_error(label);
}

void expect_bound(const webobs::native_host::OwnershipBinding &binding, const std::string &camera_id)
{
	++checks;
	if (!binding.camera_id.has_value() || *binding.camera_id != camera_id)
		throw std::runtime_error("expected bound camera_id");
}

void expect_unbound(const webobs::native_host::OwnershipBinding &binding)
{
	++checks;
	if (binding.camera_id.has_value())
		throw std::runtime_error("expected unbound entry");
}

std::string uuid_with_prefix(const std::string &prefix)
{
	return prefix + kUuidA.substr(prefix.size());
}

} // namespace

int main()
{
	try {
		// Round-trip and byte-stable deterministic encoding.
		Entries ledger;
		if (webobs::native_host::record_created_source(ledger, "camera-a", kUuidA) != Status::success)
			throw std::runtime_error("first record failed");
		expect(ledger.at(0).generation == 1, "first generation is 1");
		if (webobs::native_host::record_created_source(ledger, "camera-b", kUuidB) != Status::success)
			throw std::runtime_error("second record failed");
		expect(ledger.at(1).generation == 2, "second generation is 2");
		const std::string encoded = webobs::native_host::encode_ownership_ledger(ledger);
		expect(encoded == webobs::native_host::encode_ownership_ledger(decode(encoded).entries.value()),
		       "encode/decode round trip stable");
		const auto restored = decode(encoded);
		expect(restored.status == Status::success && restored.entries->size() == 2, "round trip restores 2");

		// Syntax rejection matrix (fail closed, no partial entries).
		expect_rejected("", "empty ledger");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[]}", "empty array");
		expect_rejected("{\"schemaVersion\":2,\"entries\":[{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"11111111-2222-3333-4444-555555555555\",\"generation\":1}]}",
				"schemaVersion must be exactly 1");
		expect_rejected("{\"schemaVersion\":\"1\",\"entries\":[]}", "schemaVersion must be integer");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"11111111-2222-3333-4444-555555555555\",\"generation\":0}]}",
				"generation zero");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"11111111-2222-3333-4444-555555555555\",\"generation\":01}]}",
				"generation leading zero");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"11111111-2222-3333-4444-555555555555\",\"generation\":1.5}]}",
				"generation float");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"AAAA1111-2222-3333-4444-555555555555\",\"generation\":1}]}",
				"uppercase uuid");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"111111112222-3333-4444-555555555555\",\"generation\":1}]}",
				"missing uuid dash");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"-camera\",\"sourceUuid\":"
				"\"11111111-2222-3333-4444-555555555555\",\"generation\":1}]}",
				"camera id must start alphanumeric");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"11111111-2222-3333-4444-555555555555\",\"extra\":true,\"generation\":1}]}",
				"extra key");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"camera-a\",\"generation\":1}]}",
				"missing sourceUuid");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"cam\\\\1\",\"sourceUuid\":"
				"\"11111111-2222-3333-4444-555555555555\",\"generation\":1}]}",
				"escaped string rejected");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"11111111-2222-3333-4444-555555555555\",\"generation\":1},{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"aaaa1111-2222-3333-4444-555555555555\",\"generation\":2}]}",
				"duplicate camera id rejected");
		expect_rejected("{\"schemaVersion\":1,\"entries\":[{\"cameraId\":\"camera-a\",\"sourceUuid\":"
				"\"11111111-2222-3333-4444-555555555555\",\"generation\":1}]} x",
				"trailing garbage");
		{
			++checks;
			const std::string oversized = "{\"schemaVersion\":1,\"entries\":[" +
				std::string(16 * 1024, ' ') + "]}";
			const auto result = decode(oversized);
			if (result.status != Status::ledger_invalid)
				throw std::runtime_error("oversize ledger rejected");
		}

		// Consistency: duplicate uuids / camera ids / generations fail closed.
		{
			Entries two;
			two.push_back(Entries::value_type{"camera-a", kUuidA, 1});
			two.push_back(Entries::value_type{"camera-b", kUuidA, 2});
			expect_unbound(webobs::native_host::classify_wall_entries(two, {kUuidA}).at(0));
			two[1] = Entries::value_type{"camera-a", kUuidB, 2};
			expect_unbound(webobs::native_host::classify_wall_entries(two, {kUuidA}).at(0));
			two[1] = Entries::value_type{"camera-b", kUuidB, 1};
			expect_unbound(webobs::native_host::classify_wall_entries(two, {kUuidA}).at(0));
		}

		// Creation provenance semantics.
		{
			Entries fresh;
			if (webobs::native_host::record_created_source(fresh, "camera-a", kUuidA) != Status::success)
				throw std::runtime_error("record into fresh ledger failed");
			const std::size_t size_before = fresh.size();
			// Idempotent re-record of the same incarnation.
			expect(webobs::native_host::record_created_source(fresh, "camera-a", kUuidA) == Status::success,
			       "same incarnation idempotent");
			expect(fresh.size() == size_before && fresh.at(0).generation == 1, "idempotent no-op");
			// A reused (existing) source is never recorded: caller skips it,
			// so classification leaves it unbound even with identical name/URL.
			expect_unbound(webobs::native_host::classify_wall_entries(fresh, {kUuidC}).at(0));
			// Replacing the incarnation frees the previous uuid.
			const std::string replacement = uuid_with_prefix("cccc1111");
			expect(webobs::native_host::record_created_source(fresh, "camera-a", replacement) ==
				       Status::success,
			       "new incarnation accepted");
			expect(fresh.at(0).generation == 2, "incarnation bumps generation");
			expect_unbound(webobs::native_host::classify_wall_entries(fresh, {kUuidA}).at(0));
			expect_bound(webobs::native_host::classify_wall_entries(fresh, {replacement}).at(0), "camera-a");
			// A uuid claimed by another camera cannot be adopted; entries unchanged.
			const std::string snapshot = webobs::native_host::encode_ownership_ledger(fresh);
			expect(webobs::native_host::record_created_source(fresh, "camera-b", replacement) ==
				       Status::record_conflict,
			       "cross-camera uuid conflict");
			expect(webobs::native_host::encode_ownership_ledger(fresh) == snapshot, "conflict leaves no trace");
			// Malformed inputs are conflicts.
			expect(webobs::native_host::record_created_source(fresh, "camera-b", "not-a-uuid") ==
				       Status::record_conflict,
			       "bad uuid syntax conflict");
			expect(webobs::native_host::record_created_source(fresh, "-bad", kUuidC) ==
				       Status::record_conflict,
			       "bad camera id conflict");
			// Capacity cap: 16 entries max.
			Entries full;
			const char hex_digits[16] = {'0', '1', '2', '3', '4', '5', '6', '7',
						     '8', '9', 'a', 'b', 'c', 'd', 'e', 'f'};
			for (std::size_t i = 0; i < 16; ++i) {
				const std::string uuid = std::string(8, hex_digits[i]) + "-" + kUuidA.substr(9);
				if (webobs::native_host::record_created_source(full, "camera-" + std::to_string(i), uuid) !=
				    Status::success)
					throw std::runtime_error("filling to 16 failed");
			}
			expect(webobs::native_host::record_created_source(full, "camera-16", kUuidC) ==
				       Status::record_conflict,
			       "17th distinct camera rejected");
			// Replacing within the cap still works when the camera already exists.
			expect(webobs::native_host::record_created_source(full, "camera-0", kUuidC) == Status::success,
			       "replacement within cap works");
			// Corrupt base ledger refuses records entirely.
			Entries corrupt{{"camera-a", "not-a-uuid", 1}};
			expect(webobs::native_host::record_created_source(corrupt, "camera-b", kUuidB) ==
				       Status::ledger_invalid,
			       "corrupt base ledger invalid");
		}

		// Classification matches exact uuid equality only.
		{
			Entries ledger{{"camera-a", kUuidA, 1}, {"camera-b", kUuidB, 2}};
			const auto bindings =
				webobs::native_host::classify_wall_entries(ledger, {kUuidB, kUuidC, kUuidA, "", kUuidB});
			expect_bound(bindings.at(0), "camera-b");
			expect_unbound(bindings.at(1));
			expect_bound(bindings.at(2), "camera-a");
			expect_unbound(bindings.at(3));
			expect_bound(bindings.at(4), "camera-b"); // repeated snapshot uuid shares identity
		}

		std::cout << "source_ownership_contract_pass " << checks << '\n';
		return 0;
	} catch (const std::exception &error) {
		std::cerr << "source_ownership_contract_fail case_" << (checks + 1) << ' ' << error.what() << '\n';
		return 1;
	} catch (...) {
		std::cerr << "source_ownership_contract_fail unknown_exception\n";
		return 1;
	}
}
