// End-to-end decision/execution flow regression over a REAL SessionStore
// (private temporary SQLite) with injected catalog, provider, backend, target,
// backup storage and deterministic clock. No OBS, network, media or profile.
#include "wall_apply_flow.hpp"

#include <cstdio>
#include <cstdlib>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef WEBOBS_TEST_TMPDIR
#define WEBOBS_TEST_TMPDIR "/tmp"
#endif

namespace {

using webobs::native_host::CameraCatalogEntry;
using webobs::native_host::execute_wall_apply_flow;
using webobs::native_host::OwnershipEntry;
using webobs::native_host::WallApplyBackupReader;
using webobs::native_host::WallApplyBackupWriter;
using webobs::native_host::WallApplyEntry;
using webobs::native_host::WallApplyFlow;
using webobs::native_host::WallApplyFlowStatus;
using webobs::native_host::WallApplyOpKind;
using webobs::native_host::WallApplyTarget;
using webobs::native_host::WallApplyUndoKind;
using webobs::native_host::WallSnapshot;

void require(bool condition, const char *message)
{
	if (!condition) {
		std::fprintf(stderr, "wall apply flow test failed: %s\n", message);
		std::exit(1);
	}
}

std::string uuid_at(char marker)
{
	std::string uuid = "11111111-2222-3333-4444-555555555555";
	uuid[0] = marker;
	return uuid;
}

WallSnapshot five_snapshot()
{
	WallSnapshot snapshot;
	snapshot.scene_uuid = uuid_at('s');
	for (int index = 0; index < 5; ++index) {
		snapshot.entries[static_cast<std::size_t>(index)] =
			webobs::native_host::WallSnapshotEntry{100 + index, uuid_at(static_cast<char>('a' + index)), true};
	}
	return snapshot;
}

std::vector<OwnershipEntry> five_ledger()
{
	std::vector<OwnershipEntry> ledger;
	for (int index = 0; index < 5; ++index)
		ledger.push_back({"cam-" + std::to_string(index), uuid_at(static_cast<char>('a' + index)),
				  static_cast<std::uint64_t>(index + 1)});
	return ledger;
}

std::vector<WallApplyEntry> same_as_ledger()
{
	std::vector<WallApplyEntry> desired;
	for (int index = 0; index < 5; ++index)
		desired.push_back({"cam-" + std::to_string(index), uuid_at(static_cast<char>('a' + index))});
	return desired;
}

// cam-0..3 unchanged, cam-4 removed, cam-5 added: one destructive operation.
std::vector<WallApplyEntry> migration_desired()
{
	return {{"cam-0", uuid_at('a')}, {"cam-1", uuid_at('b')}, {"cam-2", uuid_at('c')}, {"cam-3", uuid_at('d')},
		{"cam-5", uuid_at('6')}};
}

std::vector<CameraCatalogEntry> five_catalog()
{
	std::vector<CameraCatalogEntry> catalog;
	for (int index = 0; index < 5; ++index)
		catalog.push_back({"cam-" + std::to_string(index), true});
	return catalog;
}

const webobs::SessionIdentity kIdentity{std::string(32, 'a'), std::string(32, 'b')};

std::string temp_dir()
{
	for (const char *name : {"TMPDIR", "TEMP", "TMP"}) {
		const char *value = std::getenv(name);
		if (value != nullptr && value[0] != '\0')
			return std::string(value);
	}
	return std::string(WEBOBS_TEST_TMPDIR);
}

class TempStore {
public:
	TempStore()
		: path_(temp_dir() + "/webobs-wall-apply-flow-" + std::to_string(std::rand()) + ".sqlite"),
		  store_(path_, std::chrono::seconds(3600), false)
	{
		require(!store_.initialize().has_value(), "session store must initialize");
	}
	~TempStore() { std::remove(path_.c_str()); }
	webobs::SessionStore &store() { return store_; }

private:
	std::string path_;
	webobs::SessionStore store_;
};

struct BackendTrace {
	std::size_t calls = 0;
	std::vector<std::string> requests;
};

webobs::NativeAuthorizationBackend recording_backend(BackendTrace &trace, std::size_t allow_prefix = static_cast<std::size_t>(-1))
{
	return [&trace, allow_prefix](std::string_view principal, const webobs::SessionIdentity &identity,
				      std::string_view permission, std::string_view resource) {
		++trace.calls;
		trace.requests.emplace_back(std::string(permission) + ":" + std::string(resource));
		require(principal == "operator-user", "backend principal mismatch");
		require(identity.user_id == kIdentity.user_id && identity.auth_epoch == kIdentity.auth_epoch,
			"backend identity mismatch");
		return trace.calls > allow_prefix ? webobs::NativeAuthorizationDecision::denied
						  : webobs::NativeAuthorizationDecision::allowed;
	};
}

struct ProviderTrace {
	std::size_t calls = 0;
	bool throw_second = false;
	std::optional<WallSnapshot> second;
	std::function<std::optional<WallSnapshot>()> make()
	{
		return [this]() -> std::optional<WallSnapshot> {
			++calls;
			if (calls == 1)
				return five_snapshot();
			if (throw_second)
				throw std::runtime_error("second observation failed");
			if (second)
				return second;
			return five_snapshot();
		};
	}
};

struct FakeTarget {
	std::size_t forward_calls = 0;
	std::size_t undo_calls = 0;
	long fail_forward_at = -1;
	long fail_undo_at = -1;

	WallApplyTarget make()
	{
		WallApplyTarget target;
		target.apply = [this](WallApplyOpKind, std::string_view, std::string_view, std::string_view) {
			return static_cast<long>(forward_calls++) != fail_forward_at;
		};
		target.undo = [this](WallApplyUndoKind, std::string_view, std::string_view) {
			return static_cast<long>(undo_calls++) != fail_undo_at;
		};
		return target;
	}
};

struct FakeStorage {
	std::vector<unsigned char> material = {'s', 'e', 't', 't', 'i', 'n', 'g', 's'};
	std::size_t reads = 0;
	std::size_t writes = 0;
	long fail_restore_at = -1;

	WallApplyBackupReader reader()
	{
		return [this](std::string_view uuid) -> std::optional<std::vector<unsigned char>> {
			++reads;
			if (uuid != uuid_at('e'))
				return std::nullopt;
			return material;
		};
	}
	WallApplyBackupWriter writer()
	{
		return [this](std::string_view uuid, const std::vector<unsigned char> &bytes) {
			const std::size_t index = writes++;
			return uuid == uuid_at('e') && bytes == material && static_cast<long>(index) != fail_restore_at;
		};
	}
};

std::string bound_token(TempStore &store)
{
	const std::optional<std::string> token = store.store().create_bound("operator-user", "", kIdentity);
	require(token.has_value(), "bound session must be created");
	return *token;
}

WallApplyFlow run(TempStore &store, const std::string &token, const std::vector<CameraCatalogEntry> &catalog,
		  const std::vector<OwnershipEntry> &ledger, const std::vector<WallApplyEntry> &desired,
		  std::function<std::optional<WallSnapshot>()> provider, const webobs::NativeAuthorizationBackend &backend,
		  FakeTarget &target, FakeStorage &storage, std::chrono::milliseconds budget)
{
	return execute_wall_apply_flow(catalog, store.store(), token, "wall-a", ledger, desired, provider, backend,
				       target.make(), storage.reader(), storage.writer(), budget);
}

void test_unauthenticated_and_forbidden()
{
	TempStore store;
	BackendTrace trace;
	ProviderTrace provider;
	FakeTarget target;
	FakeStorage storage;
	const auto backend = recording_backend(trace);

	const auto unknown = run(store, "no-such-token", five_catalog(), five_ledger(), same_as_ledger(),
				 provider.make(), backend, target, storage, std::chrono::milliseconds(5000));
	require(unknown.status == WallApplyFlowStatus::unauthenticated, "unknown token must be unauthenticated");
	require(trace.calls == 0 && provider.calls == 0 && target.forward_calls == 0 && storage.reads == 0,
		"unauthenticated must touch nothing else");

	const std::string token = bound_token(store);
	const auto denied = run(store, token, five_catalog(), five_ledger(), same_as_ledger(), provider.make(),
				recording_backend(trace, 0), target, storage, std::chrono::milliseconds(5000));
	require(denied.status == WallApplyFlowStatus::forbidden, "coarse denial must be forbidden");
	require(trace.calls == 1 && provider.calls == 0 && target.forward_calls == 0 && storage.reads == 0,
		"denied decision must stop before observation");
}

void test_catalog_refusal_before_backend()
{
	TempStore store;
	const std::string token = bound_token(store);
	BackendTrace trace;
	ProviderTrace provider;
	FakeTarget target;
	FakeStorage storage;
	auto catalog = five_catalog();
	catalog.erase(catalog.begin() + 3);

	const auto result = run(store, token, catalog, five_ledger(), same_as_ledger(), provider.make(),
				recording_backend(trace), target, storage, std::chrono::milliseconds(5000));
	require(result.status == WallApplyFlowStatus::graph_unbound, "catalog-unknown claim must be graph_unbound");
	require(trace.calls == 0 && provider.calls == 0 && target.forward_calls == 0,
		"catalog refusal must precede backend and observation");
}

void test_noop_observes_once_and_never_executes()
{
	TempStore store;
	const std::string token = bound_token(store);
	BackendTrace trace;
	ProviderTrace provider;
	FakeTarget target;
	FakeStorage storage;

	const auto result = run(store, token, five_catalog(), five_ledger(), same_as_ledger(), provider.make(),
				recording_backend(trace), target, storage, std::chrono::milliseconds(5000));
	require(result.status == WallApplyFlowStatus::noop, "identical wall must be noop");
	require(provider.calls == 1, "noop performs exactly one observation");
	require(target.forward_calls == 0 && storage.reads == 0 && storage.writes == 0,
		"noop never executes or captures");
	require(result.authorization.backend_calls == 6, "one whole-batch pass covers scene plus five cameras");
}

void test_applied_migration()
{
	TempStore store;
	const std::string token = bound_token(store);
	BackendTrace trace;
	ProviderTrace provider;
	FakeTarget target;
	FakeStorage storage;

	const auto result = run(store, token, five_catalog(), five_ledger(), migration_desired(), provider.make(),
				recording_backend(trace), target, storage, std::chrono::milliseconds(5000));
	require(result.status == WallApplyFlowStatus::applied, "migration must apply");
	require(provider.calls == 2, "execution needs a second fresh observation");
	require(target.forward_calls == 2, "one remove and one add reach the target");
	require(storage.reads == 1 && storage.writes == 0, "only the destroyed source is captured");
	require(result.execution.captured_entries == 1, "the capture is reported");
}

void test_forward_failure_rolls_back_and_restores()
{
	TempStore store;
	const std::string token = bound_token(store);
	BackendTrace trace;
	ProviderTrace provider;
	FakeTarget target;
	target.fail_forward_at = 1; // the add fails after the remove applied
	FakeStorage storage;

	const auto result = run(store, token, five_catalog(), five_ledger(), migration_desired(), provider.make(),
				recording_backend(trace), target, storage, std::chrono::milliseconds(5000));
	require(result.status == WallApplyFlowStatus::rolled_back, "failed prefix must be undone");
	require(result.execution.execution.applied_operations == 1, "one forward operation applied");
	require(target.undo_calls == 1 && storage.writes == 1, "undo then restore happens once");
	require(result.execution.restore.complete, "the captured settings are restored");
}

void test_incomplete_rollbacks()
{
	{
		TempStore store;
		const std::string token = bound_token(store);
		BackendTrace trace;
		ProviderTrace provider;
		FakeTarget target;
		target.fail_forward_at = 1;
		target.fail_undo_at = 0;
		FakeStorage storage;
		const auto result = run(store, token, five_catalog(), five_ledger(), migration_desired(), provider.make(),
					recording_backend(trace), target, storage, std::chrono::milliseconds(5000));
		require(result.status == WallApplyFlowStatus::rollback_incomplete, "failed undo is reported");
		require(storage.writes == 0, "unknown target state receives no settings");
	}
	{
		TempStore store;
		const std::string token = bound_token(store);
		BackendTrace trace;
		ProviderTrace provider;
		FakeTarget target;
		target.fail_forward_at = 1;
		FakeStorage storage;
		storage.fail_restore_at = 0;
		const auto result = run(store, token, five_catalog(), five_ledger(), migration_desired(), provider.make(),
					recording_backend(trace), target, storage, std::chrono::milliseconds(5000));
		require(result.status == WallApplyFlowStatus::rollback_settings_incomplete,
			"failed settings restore is reported");
		require(result.execution.restore.failed == 1, "restore failure is counted");
	}
}

void test_stale_second_observation()
{
	TempStore store;
	const std::string token = bound_token(store);
	BackendTrace trace;
	ProviderTrace provider;
	auto changed = five_snapshot();
	changed.entries[4].source_uuid = uuid_at('9');
	provider.second = changed;
	FakeTarget target;
	FakeStorage storage;

	const auto result = run(store, token, five_catalog(), five_ledger(), migration_desired(), provider.make(),
				recording_backend(trace), target, storage, std::chrono::milliseconds(5000));
	require(result.status == WallApplyFlowStatus::stale_plan, "changed graph must be stale");
	require(target.forward_calls == 0 && storage.writes == 0, "stale plan never mutates");
}

void test_failed_second_observation()
{
	TempStore store;
	const std::string token = bound_token(store);
	BackendTrace trace;
	ProviderTrace provider;
	provider.throw_second = true;
	FakeTarget target;
	FakeStorage storage;

	const auto result = run(store, token, five_catalog(), five_ledger(), migration_desired(), provider.make(),
				recording_backend(trace), target, storage, std::chrono::milliseconds(5000));
	require(result.status == WallApplyFlowStatus::unavailable, "failed revalidation observation is unavailable");
	require(target.forward_calls == 0 && storage.reads == 0, "nothing mutates or is captured");
}

void test_invalid_budget()
{
	TempStore store;
	const std::string token = bound_token(store);
	BackendTrace trace;
	ProviderTrace provider;
	FakeTarget target;
	FakeStorage storage;

	const auto result = run(store, token, five_catalog(), five_ledger(), same_as_ledger(), provider.make(),
				recording_backend(trace), target, storage, std::chrono::milliseconds(0));
	require(result.status == WallApplyFlowStatus::invalid_request, "zero budget is invalid");
	require(trace.calls == 0 && provider.calls == 0 && target.forward_calls == 0, "invalid input touches nothing");
}

} // namespace

int main()
{
	test_unauthenticated_and_forbidden();
	test_catalog_refusal_before_backend();
	test_noop_observes_once_and_never_executes();
	test_applied_migration();
	test_forward_failure_rolls_back_and_restores();
	test_incomplete_rollbacks();
	test_stale_second_observation();
	test_failed_second_observation();
	test_invalid_budget();
	std::fprintf(stderr, "wall apply flow tests passed\n");
	return 0;
}
