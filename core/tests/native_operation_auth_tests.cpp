#include "webobs/native_operation_auth.hpp"

#include <chrono>
#include <exception>
#include <functional>
#include <iostream>
#include <string>
#include <vector>

namespace {

using namespace webobs;
using clock_point = std::chrono::steady_clock::time_point;

void require(bool condition, const char *message)
{
    if (!condition)
        throw std::runtime_error(message);
}

SessionIdentity valid_identity()
{
    return {"0123456789abcdef0123456789abcdef", "fedcba9876543210fedcba9876543210"};
}

struct RecordedCall {
    std::string principal;
    std::string permission;
    std::string resource;
};

class ScriptedBackend {
public:
    explicit ScriptedBackend(std::vector<NativeAuthorizationDecision> script) : script_(std::move(script)) {}

    NativeAuthorizationDecision operator()(std::string_view principal, const SessionIdentity &,
        std::string_view permission, std::string_view resource)
    {
        calls.push_back({std::string(principal), std::string(permission), std::string(resource)});
        if (calls.size() > script_.size())
            throw std::runtime_error("backend called past scripted length");
        return script_[calls.size() - 1];
    }

    std::vector<RecordedCall> calls;

private:
    std::vector<NativeAuthorizationDecision> script_;
};

class FakeClock {
public:
    explicit FakeClock(clock_point start = clock_point{}) : current_(start) {}

    clock_point operator()()
    {
        if (throw_on_call)
            throw std::runtime_error("clock failure must not relay text");
        const auto value = current_;
        if (step_after_read > std::chrono::milliseconds::zero())
            current_ += step_after_read;
        return value;
    }

    void advance(std::chrono::milliseconds delta) { current_ += delta; }

    bool throw_on_call = false;
    std::chrono::milliseconds step_after_read{0};

private:
    clock_point current_;
};

std::vector<NativeOperationRequirement> wall_requirements()
{
    return {
        {"scene.write", "wall-a"},
        {"live.view", "camera-1"},
        {"live.view", "camera-2"},
        {"live.view", "camera-3"},
        {"live.view", "camera-4"},
        {"live.view", "camera-5"},
    };
}

void test_all_allowed_preserves_order()
{
    ScriptedBackend backend(std::vector<NativeAuthorizationDecision>(6, NativeAuthorizationDecision::allowed));
    FakeClock clock;
    const auto requirements = wall_requirements();
    const auto result = authorize_operation("operator-one", valid_identity(), requirements,
        NativeAuthorizationBackend(std::ref(backend)), std::chrono::milliseconds(5000), clock);
    require(result.allowed(), "all-allowed must allow");
    require(result.evaluated == 6, "evaluated must equal total");
    require(backend.calls.size() == 6, "backend must be called once per requirement");
    require(backend.calls[0].permission == "scene.write" && backend.calls[0].resource == "wall-a",
        "coarse requirement must stay first");
    require(backend.calls[5].permission == "live.view" && backend.calls[5].resource == "camera-5",
        "camera order must be preserved");
    for (const auto &call : backend.calls)
        require(call.principal == "operator-one", "principal forwarded unchanged");
}

void test_denied_stops_forbidden()
{
    ScriptedBackend backend({NativeAuthorizationDecision::allowed, NativeAuthorizationDecision::denied,
        NativeAuthorizationDecision::allowed});
    FakeClock clock;
    const std::vector<NativeOperationRequirement> requirements = {
        {"scene.write", "wall-a"}, {"live.view", "camera-1"}, {"live.view", "camera-2"}};
    const auto result = authorize_operation("operator-one", valid_identity(), requirements,
        NativeAuthorizationBackend(std::ref(backend)), std::chrono::milliseconds(5000), clock);
    require(result.status == NativeOperationStatus::forbidden, "explicit deny must forbid");
    require(result.evaluated == 1, "only allowed prefix evaluated");
    require(backend.calls.size() == 2, "evaluation must stop at the denial");
}

void test_unknown_user_stops_binding_invalid()
{
    ScriptedBackend backend({NativeAuthorizationDecision::allowed, NativeAuthorizationDecision::unknown_user,
        NativeAuthorizationDecision::allowed});
    FakeClock clock;
    const std::vector<NativeOperationRequirement> requirements = {
        {"scene.write", "wall-a"}, {"live.view", "camera-1"}, {"live.view", "camera-2"}};
    const auto result = authorize_operation("operator-one", valid_identity(), requirements,
        NativeAuthorizationBackend(std::ref(backend)), std::chrono::milliseconds(5000), clock);
    require(result.status == NativeOperationStatus::binding_invalid,
        "mid-operation identity loss must stop as binding_invalid");
    require(backend.calls.size() == 2, "later requirements must be skipped");
}

void test_backend_unavailable_stops()
{
    ScriptedBackend backend({NativeAuthorizationDecision::unavailable, NativeAuthorizationDecision::allowed});
    FakeClock clock;
    const std::vector<NativeOperationRequirement> requirements = {
        {"scene.write", "wall-a"}, {"live.view", "camera-1"}};
    const auto result = authorize_operation("operator-one", valid_identity(), requirements,
        NativeAuthorizationBackend(std::ref(backend)), std::chrono::milliseconds(5000), clock);
    require(result.status == NativeOperationStatus::unavailable, "backend outage must be unavailable");
    require(backend.calls.size() == 1, "no retry or continue past outage");
}

void test_invalid_inputs_call_no_backend()
{
    ScriptedBackend backend({NativeAuthorizationDecision::allowed});
    FakeClock clock;
    const auto backend_fn = NativeAuthorizationBackend(std::ref(backend));
    const std::vector<NativeOperationRequirement> ok = {{"scene.write", "wall-a"}};

    auto bad = valid_identity();
    bad.user_id = "0123456789ABCDEF0123456789abcdef";
    require(authorize_operation("operator-one", bad, ok, backend_fn, std::chrono::milliseconds(1000), clock)
                .status == NativeOperationStatus::invalid_request,
        "uppercase identity must be invalid_request");

    bad = valid_identity();
    bad.auth_epoch = std::string(31, 'a');
    require(authorize_operation("operator-one", bad, ok, backend_fn, std::chrono::milliseconds(1000), clock)
                .status == NativeOperationStatus::invalid_request,
        "31-char epoch must be invalid_request");

    require(authorize_operation("operator-one", valid_identity(), std::span<const NativeOperationRequirement>{},
        backend_fn, std::chrono::milliseconds(1000), clock)
                .status == NativeOperationStatus::invalid_request,
        "empty requirement set must be invalid_request");

    const std::vector<NativeOperationRequirement> dup = {{"live.view", "camera-1"}, {"live.view", "camera-1"}};
    require(authorize_operation("operator-one", valid_identity(), dup, backend_fn,
        std::chrono::milliseconds(1000), clock)
                .status == NativeOperationStatus::invalid_request,
        "duplicate pair must be invalid_request");

    // Views must not refer to temporary strings, even in a rejected fixture.
    const std::vector<std::string> resources = [] {
        std::vector<std::string> items;
        for (int i = 0; i < 17; ++i)
            items.push_back("camera-" + std::to_string(i));
        return items;
    }();
    std::vector<NativeOperationRequirement> many;
    for (const auto &resource : resources)
        many.push_back({"live.view", resource});
    require(authorize_operation("operator-one", valid_identity(), many, backend_fn,
        std::chrono::milliseconds(1000), clock)
                .status == NativeOperationStatus::invalid_request,
        "over-cap requirement count must be invalid_request");

    require(authorize_operation("", valid_identity(), ok, backend_fn, std::chrono::milliseconds(1000), clock)
                .status == NativeOperationStatus::invalid_request,
        "empty principal must be invalid_request");

    require(authorize_operation("operator-one", valid_identity(), ok, backend_fn,
        std::chrono::milliseconds(0), clock)
                .status == NativeOperationStatus::invalid_request,
        "non-positive budget must be invalid_request");

    const std::vector<NativeOperationRequirement> control = {{"live.vi" "\x01" "ew", "camera-1"}};
    require(authorize_operation("operator-one", valid_identity(), control, backend_fn,
        std::chrono::milliseconds(1000), clock)
                .status == NativeOperationStatus::invalid_request,
        "control character permission must be invalid_request");

    require(authorize_operation("operator-one", valid_identity(), ok, backend_fn,
        std::chrono::milliseconds::max(), clock).status == NativeOperationStatus::invalid_request,
        "unrepresentable steady-clock budget must be invalid_request");
    require(backend.calls.empty(), "invalid inputs must produce zero backend calls");
}

void test_budget_boundary_and_exhaustion()
{
    ScriptedBackend backend(std::vector<NativeAuthorizationDecision>(6, NativeAuthorizationDecision::allowed));
    FakeClock clock;
    const auto requirements = wall_requirements();
    // Budget exactly equal to elapsed stops fail-closed before the call. The
    // start read returns time 0; the first loop check reads the budget value.
    clock.step_after_read = std::chrono::milliseconds(4000);
    const auto exact = authorize_operation("operator-one", valid_identity(), requirements,
        NativeAuthorizationBackend(std::ref(backend)), std::chrono::milliseconds(4000), clock);
    require(exact.status == NativeOperationStatus::unavailable, "elapsed == budget must stop before any call");
    require(backend.calls.empty(), "exact-budget case must spend zero backend calls");

    ScriptedBackend backend2(std::vector<NativeAuthorizationDecision>(6, NativeAuthorizationDecision::allowed));
    FakeClock clock2;
    // Each evaluation consumes 4000ms; budget 5000ms admits exactly two.
    auto limited = NativeAuthorizationBackend([&](std::string_view principal, const SessionIdentity &identity,
                                       std::string_view permission, std::string_view resource) {
        const auto decision = backend2(principal, identity, permission, resource);
        clock2.advance(std::chrono::milliseconds(4000));
        return decision;
    });
    const auto result = authorize_operation("operator-one", valid_identity(), requirements, limited,
        std::chrono::milliseconds(5000), std::ref(clock2));
    require(result.status == NativeOperationStatus::unavailable, "budget exhaustion must be unavailable");
    require(backend2.calls.size() == 2, "third requirement must be skipped once budget is spent");
}

void test_final_reply_must_arrive_before_budget()
{
    const std::vector<NativeOperationRequirement> one = {{"live.view", "camera-1"}};
    for (const auto elapsed : {4999, 5000, 5001}) {
        FakeClock clock;
        std::size_t calls = 0;
        NativeAuthorizationBackend backend = [&](std::string_view, const SessionIdentity &,
                                                 std::string_view, std::string_view) {
            ++calls;
            clock.advance(std::chrono::milliseconds(elapsed));
            return NativeAuthorizationDecision::allowed;
        };
        const auto result = authorize_operation("operator-one", valid_identity(), one, backend,
            std::chrono::milliseconds(5000), std::ref(clock));
        require(calls == 1, "final reply test must call backend exactly once");
        require(result.allowed() == (elapsed < 5000), "late final allow must never authorize");
        require(result.evaluated == (elapsed < 5000 ? 1u : 0u), "late reply is not a timely allowed prefix");
        if (elapsed >= 5000)
            require(result.status == NativeOperationStatus::unavailable, "deadline equality fails closed");
    }
}

void test_reply_clock_failure_and_regression_fail_closed()
{
    const std::vector<NativeOperationRequirement> one = {{"live.view", "camera-1"}};
    for (const bool throws : {false, true}) {
        FakeClock clock;
        NativeAuthorizationBackend backend = [&](std::string_view, const SessionIdentity &,
                                                 std::string_view, std::string_view) {
            if (throws)
                clock.throw_on_call = true;
            else
                clock.advance(std::chrono::milliseconds(-1));
            return NativeAuthorizationDecision::allowed;
        };
        const auto result = authorize_operation("operator-one", valid_identity(), one, backend,
            std::chrono::milliseconds(5000), std::ref(clock));
        require(result.status == NativeOperationStatus::unavailable && result.evaluated == 0,
            "unreliable completion clock must not authorize");
    }
    // Regression can remain above start: 0 -> 8 -> 7 must still fail.
    for (const std::vector<int> &samples : {std::vector<int>{0, 8, 7},
                                          std::vector<int>{0, 4, 8, 7}}) {
        std::size_t reads = 0;
        std::size_t calls = 0;
        NativeOperationClock clock = [&] {
            return clock_point{} + std::chrono::milliseconds(samples.at(reads++));
        };
        NativeAuthorizationBackend backend = [&](std::string_view, const SessionIdentity &,
                                                 std::string_view, std::string_view) {
            ++calls;
            return NativeAuthorizationDecision::allowed;
        };
        const auto requirements = wall_requirements();
        const auto result = authorize_operation("operator-one", valid_identity(), requirements, backend,
            std::chrono::milliseconds(10), clock);
        require(result.status == NativeOperationStatus::unavailable && calls == 1,
            "relative clock regression must stop before another backend call");
        require(result.evaluated == (samples.size() == 3 ? 0u : 1u),
            "clock regression must preserve only timely allowed prefix");
        require(reads == samples.size(), "clock failure must be observed at intended boundary");
    }
    for (const auto decision : {NativeAuthorizationDecision::denied,
             NativeAuthorizationDecision::unknown_user, NativeAuthorizationDecision::unavailable,
             static_cast<NativeAuthorizationDecision>(999)}) {
        FakeClock clock;
        NativeAuthorizationBackend backend = [&](std::string_view, const SessionIdentity &,
                                                 std::string_view, std::string_view) {
            clock.advance(std::chrono::milliseconds(5000));
            return decision;
        };
        const auto result = authorize_operation("operator-one", valid_identity(), one, backend,
            std::chrono::milliseconds(5000), std::ref(clock));
        require(result.status == NativeOperationStatus::unavailable && result.evaluated == 0,
            "deadline failure takes precedence over late backend decision");
    }
}

void test_extreme_clock_interval_fails_closed()
{
    const std::vector<NativeOperationRequirement> one = {{"live.view", "camera-1"}};
    for (const bool overflow_after_call : {false, true}) {
        std::size_t reads = 0;
        std::size_t calls = 0;
        NativeOperationClock clock = [&] {
            const auto n = reads++;
            return n <= (overflow_after_call ? 1u : 0u) ? clock_point::min() : clock_point::max();
        };
        NativeAuthorizationBackend backend = [&](std::string_view, const SessionIdentity &,
                                                 std::string_view, std::string_view) {
            ++calls;
            return NativeAuthorizationDecision::allowed;
        };
        const auto result = authorize_operation("operator-one", valid_identity(), one, backend,
            std::chrono::milliseconds(5000), clock);
        require(result.status == NativeOperationStatus::unavailable && result.evaluated == 0,
            "unrepresentable elapsed interval must fail closed without arithmetic overflow");
        require(calls == (overflow_after_call ? 1u : 0u), "overflow must stop at intended boundary");
    }
}

void test_backend_exception_maps_unavailable_without_relay()
{
    auto throwing = NativeAuthorizationBackend([](std::string_view, const SessionIdentity &, std::string_view,
                                                  std::string_view) -> NativeAuthorizationDecision {
        throw std::runtime_error("secret token leaked in message");
    });
    FakeClock clock;
    const std::vector<NativeOperationRequirement> requirements = {{"scene.write", "wall-a"}};
    const auto result = authorize_operation("operator-one", valid_identity(), requirements, throwing,
        std::chrono::milliseconds(5000), clock);
    require(result.status == NativeOperationStatus::unavailable, "backend exception must be unavailable");
}

void test_clock_exception_maps_unavailable()
{
    ScriptedBackend backend({NativeAuthorizationDecision::allowed});
    FakeClock clock;
    clock.throw_on_call = true;
    const std::vector<NativeOperationRequirement> requirements = {{"scene.write", "wall-a"}};
    const auto result = authorize_operation("operator-one", valid_identity(), requirements,
        NativeAuthorizationBackend(std::ref(backend)), std::chrono::milliseconds(5000), clock);
    require(result.status == NativeOperationStatus::unavailable, "clock exception must be unavailable");
    require(backend.calls.empty(), "clock failure must not spend a backend call");
}

} // namespace

int main()
{
    try {
        test_all_allowed_preserves_order();
        test_denied_stops_forbidden();
        test_unknown_user_stops_binding_invalid();
        test_backend_unavailable_stops();
        test_invalid_inputs_call_no_backend();
        test_budget_boundary_and_exhaustion();
        test_final_reply_must_arrive_before_budget();
        test_reply_clock_failure_and_regression_fail_closed();
        test_extreme_clock_interval_fails_closed();
        test_backend_exception_maps_unavailable_without_relay();
        test_clock_exception_maps_unavailable();
    } catch (const std::exception &error) {
        std::cerr << "native operation auth test failed: " << error.what() << '\n';
        return 1;
    }
    std::cout << "native operation auth tests passed\n";
    return 0;
}
