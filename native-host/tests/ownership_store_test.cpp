// Real file-IO contract for ownership_store.cpp. This test intentionally
// touches the filesystem in a unique temporary path; it is NOT part of the
// IO-free ledger module and does not run any OBS, Qt, network or media code.
#include "ownership_store.hpp"
#include "source_ownership.hpp"

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

namespace {

using Entries = std::vector<webobs::native_host::OwnershipEntry>;
using StoreStatus = webobs::native_host::OwnershipStoreStatus;

const std::string kUuidA = "11111111-2222-3333-4444-555555555555";
const std::string kUuidB = "aaaa1111-2222-3333-4444-555555555555";

std::size_t checks = 0;

void expect(bool condition, const char *label)
{
	++checks;
	if (!condition)
		throw std::runtime_error(label);
}

std::string temp_dir()
{
	for (const char *name : {"TMPDIR", "TEMP", "TMP"}) {
		const char *value = std::getenv(name);
		if (value && *value)
			return std::string(value) + "/";
	}
	return "";
}

std::string test_path(const char *suffix)
{
	return temp_dir() + "webobs-ownership-store-test-" + std::to_string(
#if defined(_WIN32)
		_getpid()
#else
		getpid()
#endif
		) + "-" + suffix;
}

void write_raw(const std::string &path, const std::string &bytes)
{
	FILE *stream = std::fopen(path.c_str(), "wb");
	if (!stream)
		throw std::runtime_error("test could not create fixture file");
	const std::size_t written = std::fwrite(bytes.data(), 1, bytes.size(), stream);
	std::fclose(stream);
	if (written != bytes.size())
		throw std::runtime_error("test fixture write was short");
}

Entries sample_ledger()
{
	Entries ledger;
	if (webobs::native_host::record_created_source(ledger, "camera-a", kUuidA) !=
	    webobs::native_host::OwnershipStatus::success ||
	    webobs::native_host::record_created_source(ledger, "camera-b", kUuidB) !=
	    webobs::native_host::OwnershipStatus::success)
		throw std::runtime_error("fixture ledger construction failed");
	return ledger;
}

} // namespace

int main()
{
	std::vector<std::string> created;
	struct Cleanup {
		std::vector<std::string> &paths;
		~Cleanup()
		{
			for (const auto &path : paths) {
				std::remove(path.c_str());
				std::remove((path + ".tmp").c_str());
			}
		}
	};
	const Cleanup cleanup{created};
	const auto track = [&](const std::string &path) { created.push_back(path); return path; };
	try {
		// A missing file is a valid `absent` state with no entries.
		const std::string fresh = track(test_path("absent.json"));
		const auto absent = webobs::native_host::load_ownership_store(fresh);
		expect(absent.status == StoreStatus::absent && absent.entries.empty(),
			"missing ledger must load as absent");

		// Save persists byte-stable encoder output and reloads identically.
		const Entries ledger = sample_ledger();
		expect(webobs::native_host::save_ownership_store(fresh, ledger) == StoreStatus::success,
			"first save must succeed");
		expect(webobs::native_host::load_ownership_store(fresh + ".tmp").status == StoreStatus::absent,
			"rename must leave no temp file");
		{
			FILE *stream = std::fopen(fresh.c_str(), "rb");
			if (!stream)
				throw std::runtime_error("saved ledger is unreadable");
			std::string stored;
			char buffer[512];
			std::size_t read = 0;
			while ((read = std::fread(buffer, 1, sizeof(buffer), stream)) > 0)
				stored.append(buffer, read);
			std::fclose(stream);
			expect(stored == webobs::native_host::encode_ownership_ledger(ledger),
				"stored bytes must equal the deterministic encoder output");
		}
		const auto reloaded = webobs::native_host::load_ownership_store(fresh);
		expect(reloaded.status == StoreStatus::success && reloaded.entries == ledger,
			"reload must return the exact stored ledger");

		// Replacing an existing ledger keeps the newest content only.
		Entries replacement = sample_ledger();
		replacement.erase(replacement.begin());
		expect(webobs::native_host::save_ownership_store(fresh, replacement) == StoreStatus::success,
			"replace save must succeed");
		expect(webobs::native_host::load_ownership_store(fresh).entries == replacement,
			"replace save lost or mixed content");

		// An inconsistent ledger is refused BEFORE any write; old content stays.
		Entries inconsistent = sample_ledger();
		inconsistent.push_back(inconsistent.front()); // duplicate uuid+generation+camera
		expect(webobs::native_host::save_ownership_store(fresh, inconsistent) ==
			StoreStatus::invalid_ledger,
			"inconsistent ledger must be refused");
		expect(webobs::native_host::load_ownership_store(fresh).entries == replacement,
			"refused save must not alter existing content");
		expect(webobs::native_host::load_ownership_store(fresh + ".tmp").status == StoreStatus::absent,
			"refused save must not leave a temp file");

		// An empty ledger has no serializable form and is refused too.
		expect(webobs::native_host::save_ownership_store(fresh, {}) == StoreStatus::invalid_ledger,
			"empty ledger must never be persisted");

		// Corrupt and oversized files fail closed without repair.
		const std::string corrupt = track(test_path("corrupt.json"));
		write_raw(corrupt, "{not json");
		expect(webobs::native_host::load_ownership_store(corrupt).status == StoreStatus::invalid_ledger,
			"corrupt ledger must load as invalid");
		const std::string truncated = track(test_path("truncated.json"));
		const std::string encoded = webobs::native_host::encode_ownership_ledger(ledger);
		write_raw(truncated, encoded.substr(0, encoded.size() / 2));
		expect(webobs::native_host::load_ownership_store(truncated).status == StoreStatus::invalid_ledger,
			"truncated ledger must load as invalid");
		const std::string oversized = track(test_path("oversized.json"));
		write_raw(oversized, encoded + std::string(20000, 'x'));
		expect(webobs::native_host::load_ownership_store(oversized).status == StoreStatus::invalid_ledger,
			"oversized ledger must load as invalid before decoding");

		std::cout << "ownership store tests passed (" << checks << " checks)\n";
		return 0;
	} catch (const std::exception &error) {
		std::cerr << "ownership store test failed: " << error.what() << "\n";
		return 1;
	}
}
