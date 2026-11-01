#include "webobs/native_operation_auth.hpp"

#include <algorithm>
#include <cstddef>
#include <exception>

namespace webobs {
namespace {

constexpr std::size_t kMaxRequirements = 16;
constexpr std::size_t kMaxPermissionLength = 32;
constexpr std::size_t kMaxResourceLength = 128;

bool valid_hex32(std::string_view value)
{
    if (value.size() != 32)
        return false;
    for (const char c : value) {
        const auto ok = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
        if (!ok)
            return false;
    }
    return true;
}

bool valid_identity(const SessionIdentity &identity)
{
    return valid_hex32(identity.user_id) && valid_hex32(identity.auth_epoch);
}

bool valid_text(std::string_view value, std::size_t max_length)
{
    if (value.empty() || value.size() > max_length)
        return false;
    // Canonical registry names never contain NUL or control characters.
    for (const char c : value) {
        if (static_cast<unsigned char>(c) < 0x20 || static_cast<unsigned char>(c) == 0x7f)
            return false;
    }
    return true;
}

bool valid_requirements(std::span<const NativeOperationRequirement> requirements)
{
    if (requirements.empty() || requirements.size() > kMaxRequirements)
        return false;
    for (std::size_t i = 0; i < requirements.size(); ++i) {
        const auto &item = requirements[i];
        if (!valid_text(item.permission, kMaxPermissionLength) ||
            !valid_text(item.resource_id, kMaxResourceLength))
            return false;
        // A repeated exact pair would let one authority answer stand in for
        // two requirements; the trusted adapter must deduplicate upstream.
        for (std::size_t j = 0; j < i; ++j) {
            if (requirements[j].permission == item.permission &&
                requirements[j].resource_id == item.resource_id)
                return false;
        }
    }
    return true;
}

} // namespace

NativeOperationAuthorization authorize_operation(
    std::string_view principal, const SessionIdentity &identity,
    std::span<const NativeOperationRequirement> requirements,
    const NativeAuthorizationBackend &backend,
    std::chrono::milliseconds total_budget,
    NativeOperationClock now)
{
    NativeOperationAuthorization result;

    if (!valid_identity(identity) || total_budget <= std::chrono::milliseconds::zero() ||
        !valid_requirements(requirements) || !backend || principal.empty()) {
        result.status = NativeOperationStatus::invalid_request;
        return result;
    }

    std::chrono::steady_clock::time_point start;
    try {
        start = now();
    } catch (const std::exception &) {
        result.status = NativeOperationStatus::unavailable;
        return result;
    } catch (...) {
        result.status = NativeOperationStatus::unavailable;
        return result;
    }

    for (const auto &item : requirements) {
        std::chrono::steady_clock::time_point current;
        try {
            current = now();
        } catch (...) {
            result.status = NativeOperationStatus::unavailable;
            return result;
        }
        // Remaining budget <= 0 is fail-closed, so a clock exactly at the
        // budget stops before spending another backend call.
        if (current - start >= total_budget) {
            result.status = NativeOperationStatus::unavailable;
            return result;
        }

        NativeAuthorizationDecision decision = NativeAuthorizationDecision::unavailable;
        try {
            decision = backend(principal, identity, item.permission, item.resource_id);
        } catch (...) {
            // Exception text may embed credentials or URLs; never relay it.
            result.status = NativeOperationStatus::unavailable;
            return result;
        }

        switch (decision) {
        case NativeAuthorizationDecision::allowed:
            ++result.evaluated;
            break;
        case NativeAuthorizationDecision::denied:
            result.status = NativeOperationStatus::forbidden;
            return result;
        case NativeAuthorizationDecision::unknown_user:
            result.status = NativeOperationStatus::binding_invalid;
            return result;
        case NativeAuthorizationDecision::unavailable:
            result.status = NativeOperationStatus::unavailable;
            return result;
        }
        // Defensive against an invalid enum from an incomplete adapter.
        if (decision != NativeAuthorizationDecision::allowed) {
            result.status = NativeOperationStatus::unavailable;
            return result;
        }
    }

    result.status = NativeOperationStatus::allowed;
    return result;
}

} // namespace webobs
