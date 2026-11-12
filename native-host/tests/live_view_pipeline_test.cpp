// Decision-time live-view pipeline regression over the REAL SessionStore
// (private temporary SQLite) with injected snapshot provider, backend and
// deterministic clock. No OBS, no network, no media, no production profile.
#include "live_view_pipeline.hpp"
#include "source_ownership.hpp"
#include "wall_live_decision.hpp"
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
#include <system_error>
#include <vector>

#ifndef WEBOBS_TEST_TMPDIR
#define WEBOBS_TEST_TMPDIR "/tmp"
#endif

namespace {

void require(bool condition, const char *message)
{
	if (!condition) {
		std::fprintf(stderr, "live view pipeline test failed: %s\n", message);
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
			webobs::native_host::WallSnapshotEntry{
				100 + index, uuid_at(static_cast<char>('a' + index)), true};
	}
	return snapshot;
}

std::vector<webobs::native_host::OwnershipEntry> five_ledger()
{
	std::vector<webobs::native_host::OwnershipEntry> ledger;
	for (int index = 0; index < 5; ++index) {
		ledger.push_back(webobs::native_host::OwnershipEntry{
			"cam-" + std::to_string(index), uuid_at(static_cast<char>('a' + index)),
			static_cast<std::uint64_t>(index + 1)});
	}
	return ledger;
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
		: path_(temp_dir() + "/webobs-live-view-pipeline-" +
				  std::to_string(std::rand()) + ".sqlite"),
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
	std::vector<std::string> camera_ids;
	std::size_t calls = 0;
};

webobs::NativeAuthorizationBackend recording_backend(
	BackendTrace &trace, std::optional<webobs::NativeAuthorizationDecision> verdict =
							 webobs::NativeAuthorizationDecision::allowed)
{
	return [&trace, verdict](std::string_view principal, const webobs::SessionIdentity &identity,
						   std::string_view permission, std::string_view camera_id) {
		++trace.calls;
		trace.camera_ids.emplace_back(camera_id);
		require(principal == "operator-user", "backend must receive the bound principal");
		require(identity.user_id == kIdentity.user_id && identity.auth_epoch == kIdentity.auth_epoch,
			"backend must receive the exact bound identity");
		require(permission == "live.view", "pipeline must request the live.view permission");
		return verdict.value_or(webobs::NativeAuthorizationDecision::allowed);
	};
}

webobs::NativeOperationClock fixed_clock(std::vector<std::chrono::milliseconds> steps)
{
	std::size_t index = 0;
	return [steps = std::move(steps), index]() mutable {
		const std::size_t pick = index < steps.size() ? index : steps.size() - 1;
		++index;
		return std::chrono::steady_clock::time_point(
			std::chrono::milliseconds(steps[pick]));
	};
}

} // namespace

int main()
{
	std::srand(static_cast<unsigned>(std::time(nullptr)));

	// 1. Unknown token: unauthenticated with zero observation and zero backend calls.
	{
		TempStore temp;
		BackendTrace trace;
		std::size_t provider_calls = 0;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), std::string(64, 'z'), five_ledger(),
			[&provider_calls]() -> std::optional<webobs::native_host::WallSnapshot> {
				++provider_calls;
				return five_snapshot();
			},
			recording_backend(trace), std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::unauthenticated,
			"unknown token must be unauthenticated");
		require(provider_calls == 0 && trace.calls == 0, "unknown token must not observe or authorize");
	}

	// 2. Legacy unbound session: unauthenticated, zero calls, never auto-bound.
	{
		TempStore temp;
		const auto token = temp.store().create("operator-user", "legacy row");
		require(token.has_value(), "legacy session must be created");
		BackendTrace trace;
		std::size_t provider_calls = 0;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(),
			[&provider_calls]() -> std::optional<webobs::native_host::WallSnapshot> {
				++provider_calls;
				return five_snapshot();
			},
			recording_backend(trace), std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::unauthenticated,
			"legacy unbound session must be unauthenticated");
		require(provider_calls == 0 && trace.calls == 0, "legacy session must not observe or authorize");
		require(temp.store().validate_and_slide(*token).has_value(),
			"legacy row itself remains usable for the unchanged legacy protocol");
	}

	// 3. Provider failure: unavailable before any backend call.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(),
			[]() -> std::optional<webobs::native_host::WallSnapshot> { return std::nullopt; },
			recording_backend(trace), std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::unavailable,
			"provider nullopt must be unavailable");
		require(trace.calls == 0, "provider failure must precede all backend calls");
	}

	// 4. Throwing provider collapses to unavailable without content.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(),
			[]() -> std::optional<webobs::native_host::WallSnapshot> {
				throw std::runtime_error("observer internal detail");
			},
			recording_backend(trace), std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::unavailable,
			"throwing provider must collapse to unavailable");
		require(trace.calls == 0, "throwing provider must not authorize");
	}

	// 5. Inconsistent ledger: ledger_invalid with zero observation and zero calls.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		auto ledger = five_ledger();
		ledger[3].source_uuid = ledger[1].source_uuid; // duplicate UUID claim
		BackendTrace trace;
		std::size_t provider_calls = 0;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, ledger,
			[&provider_calls]() -> std::optional<webobs::native_host::WallSnapshot> {
				++provider_calls;
				return five_snapshot();
			},
			recording_backend(trace), std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::ledger_invalid,
			"violating ledger must be ledger_invalid");
		require(provider_calls == 0 && trace.calls == 0, "ledger_invalid must precede observation");
	}

	// 6. Empty ledger: every entry unbound, zero backend calls.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, {}, [] { return five_snapshot(); }, recording_backend(trace),
			std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::graph_unbound,
			"empty ledger must yield graph_unbound");
		require(trace.calls == 0, "graph_unbound must not authorize");
	}

	// 7. Snapshot entry with no exact ledger match: graph_unbound, zero calls.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		auto snapshot = five_snapshot();
		snapshot.entries[2].source_uuid = uuid_at('f'); // valid hex, but never in the ledger
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(), [&snapshot] { return snapshot; },
			recording_backend(trace), std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::graph_unbound,
			"unbound snapshot entry must be graph_unbound");
		require(trace.calls == 0, "graph_unbound must not authorize");
	}

	// 8. Snapshot violating strict syntax: invalid_request, zero calls.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		auto snapshot = five_snapshot();
		snapshot.entries[4].source_uuid = "not-a-uuid";
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(), [&snapshot] { return snapshot; },
			recording_backend(trace), std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::invalid_request,
			"malformed snapshot must be invalid_request");
		require(trace.calls == 0, "invalid_request must not authorize");
	}

	// 9. All allowed: allowed with ids in snapshot order and five fresh calls.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(), [] { return five_snapshot(); },
			recording_backend(trace), std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::allowed,
			"full allow must authorize");
		require(result.camera_ids == std::vector<std::string>{"cam-0", "cam-1", "cam-2", "cam-3", "cam-4"},
			"camera ids must follow snapshot order");
		require(result.evaluated == 5 && trace.calls == 5, "five timely decisions required");
	}

	// 10. Denial of the second camera: forbidden, later cameras untouched.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		BackendTrace trace;
		int call_index = 0;
		const webobs::NativeAuthorizationBackend backend =
			[&trace, &call_index](std::string_view, const webobs::SessionIdentity &,
				std::string_view permission, std::string_view camera_id) {
				++trace.calls;
				trace.camera_ids.emplace_back(camera_id);
				require(permission == "live.view", "live.view permission expected");
				++call_index;
				return call_index == 2 ? webobs::NativeAuthorizationDecision::denied
					: webobs::NativeAuthorizationDecision::allowed;
			};
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(), [] { return five_snapshot(); }, backend,
			std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::forbidden,
			"explicit denial must be forbidden, not unavailable");
		require(trace.calls == 2, "denial must stop the remaining cameras");
	}

	// 11. Mid-pipeline identity loss (unknown_user): unauthenticated, not forbidden.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(), [] { return five_snapshot(); },
			recording_backend(trace, webobs::NativeAuthorizationDecision::unknown_user),
			std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::unauthenticated,
			"identity loss must surface as unauthenticated");
		require(trace.calls == 1, "identity loss must stop immediately");
	}

	// 12. Backend indeterminate: unavailable.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(), [] { return five_snapshot(); },
			recording_backend(trace, webobs::NativeAuthorizationDecision::unavailable),
			std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::unavailable,
			"indeterminate backend must be unavailable");
		require(trace.calls == 1, "indeterminate verdict must stop the batch");
	}

	// 13. Budget exhausted after observation: unavailable with zero backend calls.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		BackendTrace trace;
		// start 0ms, post-session 1ms, post-provider 5000ms >= budget 5000ms.
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(), [] { return five_snapshot(); },
			recording_backend(trace), std::chrono::milliseconds(5000),
			fixed_clock({std::chrono::milliseconds(0), std::chrono::milliseconds(1),
				std::chrono::milliseconds(5000)}));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::unavailable,
			"budget exhaustion after observation must be unavailable");
		require(trace.calls == 0, "exhausted budget must never authorize");
	}

	// 14. Exhaustion inside authorization: first camera consumes the budget.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(), [] { return five_snapshot(); },
			recording_backend(trace), std::chrono::milliseconds(1000),
			fixed_clock({std::chrono::milliseconds(0), std::chrono::milliseconds(10),
				std::chrono::milliseconds(20), std::chrono::milliseconds(1000)}));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::unavailable,
			"exhausted budget inside pairing must be unavailable");
		require(trace.calls == 0, "authorizer must not call backend past the budget");
	}

	// 15. Invalid inputs: empty token and non-positive budget never touch anything.
	{
		TempStore temp;
		BackendTrace trace;
		std::size_t provider_calls = 0;
		const auto provider = [&provider_calls]() -> std::optional<webobs::native_host::WallSnapshot> {
			++provider_calls;
			return five_snapshot();
		};
		const auto empty_token = webobs::native_host::authorize_live_view(
			temp.store(), "", five_ledger(), provider, recording_backend(trace),
			std::chrono::milliseconds(1000));
		require(empty_token.status == webobs::native_host::LiveViewPipelineStatus::invalid_request,
			"empty token must be invalid_request");
		const auto zero_budget = webobs::native_host::authorize_live_view(
			temp.store(), std::string(64, 'c'), five_ledger(), provider, recording_backend(trace),
			std::chrono::milliseconds(0));
		require(zero_budget.status == webobs::native_host::LiveViewPipelineStatus::invalid_request,
			"non-positive budget must be invalid_request");
		require(provider_calls == 0 && trace.calls == 0, "invalid inputs must not observe or authorize");
	}

	// 16. Revoked session after creation: token no longer validates.
	{
		TempStore temp;
		const auto token = temp.store().create_bound("operator-user", "login", kIdentity);
		require(token.has_value(), "bound session must be created");
		require(temp.store().revoke_identity("operator-user", kIdentity) == 1,
			"exact revocation must remove the bound session");
		BackendTrace trace;
		const auto result = webobs::native_host::authorize_live_view(
			temp.store(), *token, five_ledger(), [] { return five_snapshot(); },
			recording_backend(trace), std::chrono::milliseconds(5000));
		require(result.status == webobs::native_host::LiveViewPipelineStatus::unauthenticated,
			"revoked session must be unauthenticated");
		require(trace.calls == 0, "revoked session must not authorize");
	}

	std::printf("live view pipeline tests passed\n");
	return 0;
}
