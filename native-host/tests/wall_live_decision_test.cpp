// Link this test with src/wall_live_decision.cpp and src/source_ownership.cpp
// ONLY. The decision module is pure pairing logic: no OBS, Qt, filesystem or
// network API, and it never calls inspect_existing_wall. The authorizer is an
// injected callback, so fail-closed ordering is asserted without any backend.
#include "wall_live_decision.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using webobs::native_host::CameraPermission;
using webobs::native_host::decide_wall_live_view;
using webobs::native_host::OwnershipEntry;
using webobs::native_host::WallLiveDecision;
using webobs::native_host::WallLiveDecisionStatus;
using webobs::native_host::WallLiveAuthorizer;
using webobs::native_host::WallSnapshot;
using webobs::native_host::WallSnapshotEntry;

std::size_t checks = 0;

void expect(bool condition, const char *label)
{
	++checks;
	if (!condition)
		throw std::runtime_error(label);
}

std::string uuid_at(char marker, char tail)
{
	std::string uuid = "11111111-2222-3333-4444-555555555555";
	uuid[0] = marker;
	uuid.back() = tail;
	return uuid;
}

WallSnapshot snapshot_of(const std::vector<std::string> &uuids)
{
	WallSnapshot snapshot;
	snapshot.scene_uuid = uuids.empty() ? uuid_at('1', '1') : uuids[0];
	for (std::size_t i = 0; i < snapshot.entries.size(); ++i) {
		snapshot.entries[i].item_id = static_cast<std::int64_t>(i + 1);
		snapshot.entries[i].source_uuid = i < uuids.size() ? uuids[i] : uuid_at('f', 'f');
		snapshot.entries[i].visible = true;
	}
	return snapshot;
}

std::vector<OwnershipEntry> ledger_for(const std::vector<std::string> &uuids)
{
	std::vector<OwnershipEntry> ledger;
	for (std::size_t i = 0; i < uuids.size(); ++i)
		ledger.push_back({"cam-" + std::to_string(i), uuids[i], i + 1});
	return ledger;
}

const std::vector<std::string> kFive = {uuid_at('a', '1'), uuid_at('b', '2'), uuid_at('c', '3'), uuid_at('d', '4'), uuid_at('e', '5')};

struct Recorder {
	std::vector<std::string> calls;
	CameraPermission verdict = CameraPermission::allowed;
	std::size_t deny_after = 0; // deny once this many allows happened; 0 = never
	CameraPermission thrown = CameraPermission::allowed; // unused sentinel; throwing flag below
	bool throw_on_call = false;

	WallLiveAuthorizer authorizer()
	{
		return [this](std::string_view camera_id) -> CameraPermission {
			calls.push_back(std::string(camera_id));
			if (throw_on_call)
				throw std::runtime_error("authorizer exploded");
			if (deny_after != 0 && calls.size() > deny_after)
				return CameraPermission::denied;
			return verdict;
		};
	}
};

void allowed_path()
{
	const WallSnapshot snapshot = snapshot_of(kFive);
	const std::vector<OwnershipEntry> ledger = ledger_for(kFive);
	Recorder recorder;
	const WallLiveDecision decision = decide_wall_live_view(snapshot, ledger, recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::allowed, "full pairing must allow");
	expect(decision.evaluated == 5, "all five cameras must be evaluated");
	expect(recorder.calls == std::vector<std::string>({"cam-0", "cam-1", "cam-2", "cam-3", "cam-4"}),
	       "authorizer must run in snapshot order");
	expect(decision.bound_camera_ids == recorder.calls, "allowed decision must carry snapshot-order ids");
}

void unbound_stops_before_authorizer()
{
	std::vector<std::string> uuids = kFive;
	uuids[2] = uuid_at('9', '9'); // not in ledger
	Recorder recorder;
	const WallLiveDecision decision = decide_wall_live_view(snapshot_of(uuids), ledger_for(kFive), recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::graph_unbound, "missing provenance must yield graph_unbound");
	expect(recorder.calls.empty(), "graph_unbound must never call the authorizer");
	expect(decision.bound_camera_ids.empty() && decision.evaluated == 0, "unbound decision exposes no ids");
}

void empty_ledger_is_valid_initial_state_but_unbound()
{
	Recorder recorder;
	const WallLiveDecision decision =
		decide_wall_live_view(snapshot_of(kFive), std::vector<OwnershipEntry>{}, recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::graph_unbound, "empty ledger pairs every entry as unbound");
	expect(recorder.calls.empty(), "empty ledger must not authorize anything");
}

void inconsistent_ledgers_fail_closed()
{
	std::vector<OwnershipEntry> base = ledger_for(kFive);
	Recorder recorder;

	std::vector<OwnershipEntry> duplicate_uuid = base;
	duplicate_uuid[4].source_uuid = duplicate_uuid[0].source_uuid;
	WallLiveDecision decision = decide_wall_live_view(snapshot_of(kFive), duplicate_uuid, recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::ledger_invalid && recorder.calls.empty(),
	       "duplicate uuid ledger must fail closed with zero calls");

	std::vector<OwnershipEntry> duplicate_camera = base;
	duplicate_camera[4].camera_id = duplicate_camera[0].camera_id;
	recorder.calls.clear();
	decision = decide_wall_live_view(snapshot_of(kFive), duplicate_camera, recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::ledger_invalid && recorder.calls.empty(),
	       "duplicate camera ledger must fail closed with zero calls");

	std::vector<OwnershipEntry> duplicate_generation = base;
	duplicate_generation[4].generation = duplicate_generation[0].generation;
	recorder.calls.clear();
	decision = decide_wall_live_view(snapshot_of(kFive), duplicate_generation, recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::ledger_invalid && recorder.calls.empty(),
	       "duplicate generation ledger must fail closed with zero calls");

	std::vector<OwnershipEntry> zero_generation = base;
	zero_generation[1].generation = 0;
	recorder.calls.clear();
	decision = decide_wall_live_view(snapshot_of(kFive), zero_generation, recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::ledger_invalid && recorder.calls.empty(),
	       "zero generation ledger must fail closed with zero calls");

	std::vector<OwnershipEntry> bad_syntax = base;
	bad_syntax[1].camera_id = "-leading-dash";
	recorder.calls.clear();
	decision = decide_wall_live_view(snapshot_of(kFive), bad_syntax, recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::ledger_invalid && recorder.calls.empty(),
	       "bad camera syntax ledger must fail closed with zero calls");
}

void snapshot_violations_reject_before_ledger()
{
	Recorder recorder;
	std::vector<std::string> duplicate = kFive;
	duplicate[3] = duplicate[1];
	WallLiveDecision decision = decide_wall_live_view(snapshot_of(duplicate), ledger_for(kFive), recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::invalid_request && recorder.calls.empty(),
	       "duplicate snapshot uuid must be invalid_request with zero calls");

	Recorder recorder2;
	std::vector<std::string> uppercase = kFive;
	uppercase[2] = "AAAA1111-2222-3333-4444-555555555555";
	decision = decide_wall_live_view(snapshot_of(uppercase), ledger_for(kFive), recorder2.authorizer());
	expect(decision.status == WallLiveDecisionStatus::invalid_request && recorder2.calls.empty(),
	       "uppercase snapshot uuid must be invalid_request with zero calls");

	Recorder recorder3;
	std::vector<std::string> empty_uuid = kFive;
	empty_uuid[1] = "";
	decision = decide_wall_live_view(snapshot_of(empty_uuid), ledger_for(kFive), recorder3.authorizer());
	expect(decision.status == WallLiveDecisionStatus::invalid_request && recorder3.calls.empty(),
	       "empty snapshot uuid must be invalid_request with zero calls");
}

void denial_and_unavailable_stop_immediately()
{
	std::vector<OwnershipEntry> ledger = ledger_for(kFive);
	Recorder deny_after_two;
	deny_after_two.deny_after = 2;
	WallLiveDecision decision = decide_wall_live_view(snapshot_of(kFive), ledger, deny_after_two.authorizer());
	expect(decision.status == WallLiveDecisionStatus::forbidden, "denial must yield forbidden");
	expect(deny_after_two.calls.size() == 3, "a denial must stop the sequence at that camera");
	expect(decision.evaluated == 2, "forbidden records only the accepted prefix");
	expect(decision.bound_camera_ids.empty(), "forbidden exposes no bound ids");

	Recorder unavailable;
	unavailable.verdict = CameraPermission::unavailable;
	const WallLiveDecision decision2 = decide_wall_live_view(snapshot_of(kFive), ledger, unavailable.authorizer());
	expect(decision2.status == WallLiveDecisionStatus::unavailable, "indeterminate verdict must yield unavailable");
	expect(unavailable.calls.size() == 1, "unavailable must stop at the first camera");
	expect(decision2.evaluated == 0, "unavailable accepts no prefix");
}

void throwing_authorizer_is_unavailable()
{
	Recorder recorder;
	recorder.throw_on_call = true;
	const WallLiveDecision decision = decide_wall_live_view(snapshot_of(kFive), ledger_for(kFive), recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::unavailable, "a thrown authorizer must become unavailable");
	expect(decision.bound_camera_ids.empty() && decision.evaluated == 0, "throwing decision exposes nothing");
}

void stale_ledger_uuid_replaced_by_fresh_snapshot()
{
	// A snapshot entry whose uuid was freed by an incarnation replacement pairs
	// unbound: the ledger keeps only the newest claim per camera.
	std::vector<OwnershipEntry> ledger = ledger_for(kFive);
	ledger[2].source_uuid = uuid_at('c', '9'); // camera-2 recreated, old uuid freed
	Recorder recorder;
	const WallLiveDecision decision = decide_wall_live_view(snapshot_of(kFive), ledger, recorder.authorizer());
	expect(decision.status == WallLiveDecisionStatus::graph_unbound, "freed uuid must pair unbound, not stale-bind");
	expect(recorder.calls.empty(), "stale pairing never authorizes");
}
} // namespace

int main()
{
	try {
		allowed_path();
		unbound_stops_before_authorizer();
		empty_ledger_is_valid_initial_state_but_unbound();
		inconsistent_ledgers_fail_closed();
		snapshot_violations_reject_before_ledger();
		denial_and_unavailable_stop_immediately();
		throwing_authorizer_is_unavailable();
		stale_ledger_uuid_replaced_by_fresh_snapshot();
	} catch (const std::exception &error) {
		std::cerr << "wall live decision test failed: " << error.what() << std::endl;
		return 1;
	}
	std::cout << "wall live decision tests passed (" << checks << " checks)" << std::endl;
	return 0;
}
