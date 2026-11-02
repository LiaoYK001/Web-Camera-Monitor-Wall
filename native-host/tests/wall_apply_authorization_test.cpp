// Decision-time authorized-apply pipeline regression over the REAL SessionStore
// (private temporary SQLite) with injected snapshot provider, backend and
// deterministic clock. No OBS, no network, no media, no production profile.
#include "source_ownership.hpp"
#include "wall_apply_authorization.hpp"
#include "wall_apply_plan.hpp"
#include "wall_snapshot.hpp"
#include "webobs/authentication.hpp"
#include "webobs/native_control_auth.hpp"

#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef WEBOBS_TEST_TMPDIR
#define WEBOBS_TEST_TMPDIR "/tmp"
#endif

namespace {

void require(bool condition, const char *message)
{
	if (!condition) {
		std::fprintf(stderr, "wall apply authorization test failed: %s\n", message);
		std::exit(1);
	}
}

std::string uuid_at(char marker)
{
	std::string uuid = "11111111-2222-3333-4444-555555555555";
	uuid[0] = marker;
	return uuid;
}

webobs::native_host::WallSnapshot five_snapshot()
{
	webobs::native_host::WallSnapshot snapshot;
	snapshot.scene_uuid = uuid_at('s');
	for (int index = 0; index < 5; ++index) {
		snapshot.entries[static_cast<std::size_t>(index)] =
			webobs::native_host::WallSnapshotEntry{100 + index, uuid_at(static_cast<char>('a' + index)), true};
	}
	return snapshot;
}

std::vector<webobs::native_host::OwnershipEntry> five_ledger()
{
	std::vector<webobs::native_host::OwnershipEntry> ledger;
	for (int index = 0; index < 5; ++index) {
		ledger.push_back(webobs::native_host::OwnershipEntry{
			"cam-" + std::to_string(index), uuid_at(static_cast<char>('a' + index)), static_cast<std::uint64_t>(index + 1)});
	}
	return ledger;
}

std::vector<webobs::native_host::WallApplyEntry> same_as_ledger()
{
	std::vector<webobs::native_host::WallApplyEntry> desired;
	for (int index = 0; index < 5; ++index) {
		desired.push_back(webobs::native_host::WallApplyEntry{
			"cam-" + std::to_string(index), uuid_at(static_cast<char>('a' + index))});
	}
	return desired;
}

const webobs::SessionIdentity kIdentity{std::string(32, 'a'), std::string(32, 'b')};

std::string temp_dir()
{
	for (const char *name : {"TMPDIR", "TEMP", "TMP"}) {
		const char *value = std::getenv(name);
		if (value != nullptr && value[0] != '\0') {
			return std::string(value);
		}
	}
	return std::string(WEBOBS_TEST_TMPDIR);
}

class TempStore {
public:
	TempStore()
		: path_(temp_dir() + "/webobs-wall-apply-auth-" + std::to_string(std::rand()) + ".sqlite"),
		  store_(path_, std::chrono::seconds(3600), false)
	{
		require(!store_.initialize().has_value(), "session store must initialize");
	}
	~TempStore()
	{
		std::remove(path_.c_str());
	}
	webobs::SessionStore &store() { return store_; }

private:
	std::string path_;
	webobs::SessionStore store_;
};

struct BackendTrace {
	std::vector<std::string> requests; // "permission:resource" per call
	std::size_t calls = 0;
};

// Records "permission:resource" pairs. The first `allow_prefix` calls return
// `verdict` (default allowed); any call beyond that prefix returns denied, so
// a mid-batch denial stops the authorize_operation prefix at a chosen call.
webobs::NativeAuthorizationBackend recording_backend(
	BackendTrace &trace, webobs::NativeAuthorizationDecision verdict = webobs::NativeAuthorizationDecision::allowed,
	std::size_t allow_prefix = static_cast<std::size_t>(-1))
{
	return [&trace, verdict, allow_prefix](std::string_view principal, const webobs::SessionIdentity &identity,
						   std::string_view permission, std::string_view resource) {
		++trace.calls;
		trace.requests.emplace_back(std::string(permission) + ":" + std::string(resource));
		require(principal == "operator-user", "backend must receive the bound principal");
		require(identity.user_id == kIdentity.user_id && identity.auth_epoch == kIdentity.auth_epoch,
			"backend must receive the exact bound identity");
		if (trace.calls > allow_prefix) {
			return webobs::NativeAuthorizationDecision::denied;
		}
		return verdict;
	};
}

struct ProviderTrace {
	std::size_t calls = 0;
	bool throw_error = false;
	std::optional<webobs::native_host::WallSnapshot> value = five_snapshot();
};

std::function<std::optional<webobs::native_host::WallSnapshot>()> recording_provider(ProviderTrace &trace)
{
	return [&trace]() -> std::optional<webobs::native_host::WallSnapshot> {
		++trace.calls;
		if (trace.throw_error) {
			throw std::runtime_error("injected provider failure");
		}
		return trace.value;
	};
}

webobs::NativeOperationClock fixed_clock(std::vector<std::chrono::milliseconds> steps)
{
	std::size_t index = 0;
	return [steps = std::move(steps), index]() mutable {
		const std::size_t pick = index < steps.size() ? index : steps.size() - 1;
		++index;
		return std::chrono::steady_clock::time_point(std::chrono::milliseconds(steps[pick]));
	};
}

std::string bound_token(TempStore &store)
{
	const std::optional<std::string> token = store.store().create_bound("operator-user", "", kIdentity);
	require(token.has_value(), "bound session must be created");
	return *token;
}

webobs::native_host::WallApplyAuthorization run(
	TempStore &store, const std::string &token, const std::vector<webobs::native_host::OwnershipEntry> &ledger,
	const std::vector<webobs::native_host::WallApplyEntry> &desired,
	const std::function<std::optional<webobs::native_host::WallSnapshot>()> &provider,
	const webobs::NativeAuthorizationBackend &backend, std::chrono::milliseconds budget,
	webobs::NativeOperationClock clock = webobs::NativeOperationClock{})
{
	if (clock) {
		return webobs::native_host::authorize_wall_apply(
			store.store(), token, "wall-a", ledger, desired, provider, backend, budget, std::move(clock));
	}
	return webobs::native_host::authorize_wall_apply(
		store.store(), token, "wall-a", ledger, desired, provider, backend, budget);
}

void test_unknown_and_legacy_sessions()
{
	TempStore store;
	BackendTrace trace;
	ProviderTrace provider_trace;
	const auto backend = recording_backend(trace);
	const auto provider = recording_provider(provider_trace);

	const auto unknown = run(store, "no-such-token", five_ledger(), same_as_ledger(), provider, backend,
		std::chrono::milliseconds(5000));
	require(unknown.status == webobs::native_host::WallApplyAuthorizationStatus::unauthenticated,
		"unknown token must be unauthenticated");
	require(trace.calls == 0 && provider_trace.calls == 0, "unknown session must not reach ledger or backend");

	const std::optional<std::string> legacy = store.store().create("operator-user", "");
	require(legacy.has_value(), "legacy session must be created");
	const auto legacy_result =
		run(store, *legacy, five_ledger(), same_as_ledger(), provider, backend, std::chrono::milliseconds(5000));
	require(legacy_result.status == webobs::native_host::WallApplyAuthorizationStatus::unauthenticated,
		"legacy unbound session must never adopt a binding");
	require(trace.calls == 0 && provider_trace.calls == 0, "legacy session must not reach ledger or backend");
}

void test_whole_batch_allowed_then_plan()
{
	TempStore store;
	BackendTrace trace;
	ProviderTrace provider_trace;
	const auto backend = recording_backend(trace);
	const auto provider = recording_provider(provider_trace);
	const std::string token = bound_token(store);

	const auto noop =
		run(store, token, five_ledger(), same_as_ledger(), provider, backend, std::chrono::milliseconds(5000));
	require(noop.status == webobs::native_host::WallApplyAuthorizationStatus::noop, "identical desired must be noop");
	require(noop.backend_calls == 6, "six requirements must be evaluated");
	require(provider_trace.calls == 1, "snapshot must be observed once");
	require(trace.requests.size() == 6 && trace.requests[0] == "scene.write:wall-a",
		"coarse scene.write requirement must come first");
	require(trace.requests[1] == "live.view:cam-0" && trace.requests[5] == "live.view:cam-4",
		"live.view requirements must follow in ledger order");
	require(noop.plan.operations.size() == 5 && noop.plan.rollback.empty(), "noop plan keeps everything");

	// Replace cam-2 (ledger uuid marker 'c') with a fresh UUID marker '6'.
	auto desired = same_as_ledger();
	desired[2].source_uuid = uuid_at('6');
	ProviderTrace planned_trace;
	const auto planned = run(store, token, five_ledger(), desired, recording_provider(planned_trace),
		recording_backend(trace), std::chrono::milliseconds(5000));
	require(planned.status == webobs::native_host::WallApplyAuthorizationStatus::planned, "replacement must plan");
	require(planned.plan.operations.size() == 5, "planned keeps plus one replace");
	require(planned.plan.rollback.size() == 2, "replace rollback is drop-new then restore-old");
	require(planned.plan.operations[2].kind == webobs::native_host::WallApplyOpKind::replace,
		"slot two must be a replace operation");
	require(planned.plan.rollback[0].kind == webobs::native_host::WallApplyUndoKind::drop_binding &&
			planned.plan.rollback[0].camera_id == "cam-2" && planned.plan.rollback[0].uuid == uuid_at('6'),
		"rollback must drop the new binding first");
	require(planned.plan.rollback[1].kind == webobs::native_host::WallApplyUndoKind::restore_binding &&
			planned.plan.rollback[1].camera_id == "cam-2" && planned.plan.rollback[1].uuid == uuid_at('c'),
		"rollback must then restore the old ledger binding");
}

void test_denial_and_backend_states()
{
	TempStore store;
	BackendTrace trace;
	ProviderTrace provider_trace;
	const std::string token = bound_token(store);

	const auto deny_first = run(store, token, five_ledger(), same_as_ledger(), recording_provider(provider_trace),
		recording_backend(trace, webobs::NativeAuthorizationDecision::allowed, 0), std::chrono::milliseconds(5000));
	require(deny_first.status == webobs::native_host::WallApplyAuthorizationStatus::forbidden,
		"coarse denial must forbid the whole batch");
	require(trace.calls == 1 && provider_trace.calls == 0, "denial must stop before observation");

	BackendTrace mid_trace;
	const auto deny_mid = run(store, token, five_ledger(), same_as_ledger(), recording_provider(provider_trace),
		recording_backend(mid_trace, webobs::NativeAuthorizationDecision::allowed, 2), std::chrono::milliseconds(5000));
	require(deny_mid.status == webobs::native_host::WallApplyAuthorizationStatus::forbidden,
		"mid-batch denial must forbid and stop the prefix");
	require(mid_trace.calls == 3 && provider_trace.calls == 0, "third denial stops later calls");

	BackendTrace unknown_trace;
	const auto unknown_user = run(store, token, five_ledger(), same_as_ledger(), recording_provider(provider_trace),
		recording_backend(unknown_trace, webobs::NativeAuthorizationDecision::unknown_user),
		std::chrono::milliseconds(5000));
	require(unknown_user.status == webobs::native_host::WallApplyAuthorizationStatus::unauthenticated,
		"identity loss mid-operation must be unauthenticated, never forbidden");
	require(unknown_trace.calls == 1 && provider_trace.calls == 0, "unknown user stops immediately");

	BackendTrace unavail_trace;
	const auto unavailable = run(store, token, five_ledger(), same_as_ledger(), recording_provider(provider_trace),
		recording_backend(unavail_trace, webobs::NativeAuthorizationDecision::unavailable),
		std::chrono::milliseconds(5000));
	require(unavailable.status == webobs::native_host::WallApplyAuthorizationStatus::unavailable,
		"backend outage must be unavailable");
	require(provider_trace.calls == 0, "outage must stop before observation");
}

void test_provider_states()
{
	TempStore store;
	BackendTrace trace;
	const std::string token = bound_token(store);

	ProviderTrace none_trace;
	none_trace.value = std::nullopt;
	const auto none =
		run(store, token, five_ledger(), same_as_ledger(), recording_provider(none_trace), recording_backend(trace),
			std::chrono::milliseconds(5000));
	require(none.status == webobs::native_host::WallApplyAuthorizationStatus::unavailable,
		"missing snapshot must be unavailable");
	require(none.plan.operations.empty() && none.plan.rollback.empty(), "unavailable carries no plan");

	ProviderTrace throw_trace;
	throw_trace.throw_error = true;
	const auto thrown = run(store, token, five_ledger(), same_as_ledger(), recording_provider(throw_trace),
		recording_backend(trace), std::chrono::milliseconds(5000));
	require(thrown.status == webobs::native_host::WallApplyAuthorizationStatus::unavailable,
		"throwing provider must be unavailable");
}

void test_fail_closed_inputs_before_backend()
{
	TempStore store;
	BackendTrace trace;
	ProviderTrace provider_trace;
	const std::string token = bound_token(store);
	const auto backend = recording_backend(trace);
	const auto provider = recording_provider(provider_trace);

	auto broken_ledger = five_ledger();
	broken_ledger[1].source_uuid = broken_ledger[0].source_uuid;
	const auto ledger_invalid = run(store, token, broken_ledger, same_as_ledger(), provider, backend,
		std::chrono::milliseconds(5000));
	require(ledger_invalid.status == webobs::native_host::WallApplyAuthorizationStatus::ledger_invalid,
		"inconsistent ledger must fail before backend");
	require(trace.calls == 0 && provider_trace.calls == 0, "ledger failure must not call backend or provider");

	// 16 cameras + coarse scene.write = 17 requirements exceeds the 16 cap.
	std::vector<webobs::native_host::OwnershipEntry> too_many;
	const std::string markers = "0123456789abcdef";
	for (std::size_t index = 0; index < 16; ++index) {
		too_many.push_back(webobs::native_host::OwnershipEntry{
			"cam-" + std::to_string(index), uuid_at(markers[index]), static_cast<std::uint64_t>(index + 1)});
	}
	require(webobs::native_host::ownership_ledger_consistent(too_many), "16-entry fixture must be consistent");
	const auto too_many_result = run(store, token, too_many, same_as_ledger(), provider, backend,
		std::chrono::milliseconds(5000));
	require(too_many_result.status == webobs::native_host::WallApplyAuthorizationStatus::invalid_request,
		"ledger beyond the requirement cap must be invalid_request");
	require(trace.calls == 0, "requirement cap must reject before any backend call");

	const std::string uuid_like = uuid_at('a');
	const auto uuid_resource = webobs::native_host::authorize_wall_apply(
		store.store(), token, uuid_like, five_ledger(), same_as_ledger(), provider, backend,
		std::chrono::milliseconds(5000));
	require(uuid_resource.status == webobs::native_host::WallApplyAuthorizationStatus::invalid_request,
		"UUID-shaped resource id must be refused");
	require(trace.calls == 0, "UUID resource must not spend backend calls");

	auto bad_desired = same_as_ledger();
	bad_desired[0].camera_id = "-lead";
	const auto bad_camera =
		run(store, token, five_ledger(), bad_desired, provider, backend, std::chrono::milliseconds(5000));
	require(bad_camera.status == webobs::native_host::WallApplyAuthorizationStatus::invalid_request,
		"malformed desired camera must be refused before backend");
	require(trace.calls == 0, "malformed desired must not spend backend calls");

	const std::vector<webobs::native_host::WallApplyEntry> full = same_as_ledger();
	const std::vector<webobs::native_host::WallApplyEntry> short_desired(full.begin(), full.begin() + 4);
	const auto short_result =
		run(store, token, five_ledger(), short_desired, provider, backend, std::chrono::milliseconds(5000));
	require(short_result.status == webobs::native_host::WallApplyAuthorizationStatus::invalid_request,
		"desired must be exactly five before backend");
	require(trace.calls == 0, "short desired must not spend backend calls");

	const auto zero_budget =
		run(store, token, five_ledger(), same_as_ledger(), provider, backend, std::chrono::milliseconds(0));
	require(zero_budget.status == webobs::native_host::WallApplyAuthorizationStatus::invalid_request,
		"non-positive budget must be invalid_request");
	require(trace.calls == 0 && provider_trace.calls == 0, "invalid budget must not call backend or provider");

	const auto empty_token = run(store, "", five_ledger(), same_as_ledger(), provider, backend,
		std::chrono::milliseconds(5000));
	require(empty_token.status == webobs::native_host::WallApplyAuthorizationStatus::invalid_request,
		"empty token must be invalid_request");
}

void test_budget_and_graph_unbound()
{
	TempStore store;
	BackendTrace trace;
	ProviderTrace provider_trace;
	const std::string token = bound_token(store);

	// Clock already at the budget when the authorization gate checks.
	const auto exhausted = run(store, token, five_ledger(), same_as_ledger(), recording_provider(provider_trace),
		recording_backend(trace), std::chrono::milliseconds(5000), fixed_clock({std::chrono::milliseconds(0),
			std::chrono::milliseconds(5000)}));
	require(exhausted.status == webobs::native_host::WallApplyAuthorizationStatus::unavailable,
		"exhausted budget before authorization must be unavailable");
	require(trace.calls == 0 && provider_trace.calls == 0, "exhausted budget must not call backend or provider");

	// Authorized batch but snapshot entry not bound to the ledger: plan refuses.
	auto foreign = five_snapshot();
	foreign.entries[3].source_uuid = uuid_at('f');
	ProviderTrace foreign_trace;
	foreign_trace.value = foreign;
	const auto unbound = run(store, token, five_ledger(), same_as_ledger(), recording_provider(foreign_trace),
		recording_backend(trace), std::chrono::milliseconds(5000));
	require(unbound.status == webobs::native_host::WallApplyAuthorizationStatus::graph_unbound,
		"authorized decision still needs a fully bound graph");
	require(unbound.plan.operations.empty() && unbound.plan.rollback.empty(), "unbound carries no partial plan");
}

} // namespace

int main()
{
	std::srand(static_cast<unsigned>(std::time(nullptr)));
	test_unknown_and_legacy_sessions();
	test_whole_batch_allowed_then_plan();
	test_denial_and_backend_states();
	test_provider_states();
	test_fail_closed_inputs_before_backend();
	test_budget_and_graph_unbound();
	std::fprintf(stderr, "wall apply authorization tests passed\n");
	return 0;
}
