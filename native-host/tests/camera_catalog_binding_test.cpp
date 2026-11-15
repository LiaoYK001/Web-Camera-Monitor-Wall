// Link this test with src/camera_catalog_binding.cpp, src/wall_apply_authorization.cpp,
// src/wall_apply_plan.cpp, src/wall_apply_executor.cpp, src/wall_apply_backup.cpp and
// src/source_ownership.cpp. Pure catalog classification plus the catalog-bound
// authorization wrapper over the real SessionStore; the wrapper cases live in
// wall_apply_authorization_test.cpp, so this file covers the classifier only.
#include "camera_catalog_binding.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using webobs::native_host::CameraCatalogEntry;
using webobs::native_host::CameraCatalogStatus;
using webobs::native_host::classify_camera_catalog;
using webobs::native_host::OwnershipEntry;

std::size_t checks = 0;

void expect(bool condition, const char *label)
{
	++checks;
	if (!condition)
		throw std::runtime_error(label);
}

std::string uuid_at(char marker)
{
	std::string uuid = "11111111-2222-3333-4444-555555555555";
	uuid[0] = marker;
	return uuid;
}

std::vector<OwnershipEntry> five_ledger()
{
	std::vector<OwnershipEntry> ledger;
	for (int index = 0; index < 5; ++index)
		ledger.push_back({"cam-" + std::to_string(index), uuid_at(static_cast<char>('a' + index)),
				  static_cast<std::uint64_t>(index + 1)});
	return ledger;
}

std::vector<CameraCatalogEntry> five_catalog()
{
	std::vector<CameraCatalogEntry> catalog;
	for (int index = 0; index < 5; ++index)
		catalog.push_back({"cam-" + std::to_string(index), true});
	return catalog;
}

void case_bound()
{
	const auto binding = classify_camera_catalog(five_ledger(), five_catalog());
	expect(binding.status == CameraCatalogStatus::bound, "all enabled cameras bind");
	expect(binding.entries_checked == 5, "every ledger entry checked");
}

void case_unknown_camera()
{
	auto catalog = five_catalog();
	catalog.erase(catalog.begin() + 3); // cam-3 stays in the ledger but not the catalog
	const auto binding = classify_camera_catalog(five_ledger(), catalog);
	expect(binding.status == CameraCatalogStatus::unknown_camera, "missing catalog camera is unknown");
	expect(binding.entries_checked == 4, "classification stops at the unknown claim");
}

void case_disabled_camera()
{
	auto catalog = five_catalog();
	catalog[3].enabled = false;
	const auto binding = classify_camera_catalog(five_ledger(), catalog);
	expect(binding.status == CameraCatalogStatus::disabled_camera, "disabled catalog camera is refused");
	expect(binding.entries_checked == 4, "classification stops at the disabled claim");
}

void case_invalid_catalogs()
{
	auto duplicate = five_catalog();
	duplicate[4].camera_id = duplicate[0].camera_id;
	expect(classify_camera_catalog(five_ledger(), duplicate).status == CameraCatalogStatus::invalid_catalog,
	       "duplicate catalog ids are invalid");

	auto bad_id = five_catalog();
	bad_id[0].camera_id = "-leading-dash";
	expect(classify_camera_catalog(five_ledger(), bad_id).status == CameraCatalogStatus::invalid_catalog,
	       "invalid catalog id syntax is refused");

	std::vector<CameraCatalogEntry> huge;
	for (int index = 0; index < 257; ++index)
		huge.push_back({"cam-" + std::to_string(index), true});
	expect(classify_camera_catalog(five_ledger(), huge).status == CameraCatalogStatus::invalid_catalog,
	       "oversized catalog is refused");

	// Inconsistent ledger (duplicate uuid) must fail before any claim is trusted.
	auto ledger = five_ledger();
	ledger[1].source_uuid = ledger[0].source_uuid;
	expect(classify_camera_catalog(ledger, five_catalog()).status == CameraCatalogStatus::invalid_catalog,
	       "inconsistent ledger is refused");
}

void case_empty_ledger_is_trivially_bound()
{
	const auto binding = classify_camera_catalog({}, {});
	expect(binding.status == CameraCatalogStatus::bound, "empty ledger binds vacuously");
	expect(binding.entries_checked == 0, "nothing to check");
}

} // namespace

int main()
{
	try {
		case_bound();
		case_unknown_camera();
		case_disabled_camera();
		case_invalid_catalogs();
		case_empty_ledger_is_trivially_bound();
	} catch (const std::exception &error) {
		std::cerr << "camera catalog binding test failed: " << error.what() << '\n';
		return 1;
	}
	std::cout << "camera catalog binding tests passed (" << checks << " checks)\n";
	return 0;
}
