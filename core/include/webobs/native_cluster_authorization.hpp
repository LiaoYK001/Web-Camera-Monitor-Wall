#pragma once

#include "webobs/native_control_auth.hpp"

#include <chrono>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>

namespace webobs {

struct NativeClusterAuthorizationConfig {
    std::uint16_t port = 8095;
    std::string internal_token;
    std::chrono::milliseconds connect_timeout{500};
    std::chrono::milliseconds request_timeout{2000};
};

// Renderer-free adapter for the existing loopback cluster authority. Configuration
// comes from the trusted host, NEVER a renderer request or browser credential.
class NativeClusterAuthorizationBackend {
public:
    explicit NativeClusterAuthorizationBackend(NativeClusterAuthorizationConfig config);
    [[nodiscard]] bool configured() const noexcept { return static_cast<bool>(runtime_); }
    // principal must come from NativeControlAuth's freshly validated SessionStore.
    // No grants are cached; every valid invocation performs its own bounded POST.
    // Legacy diagnostic adapter only; NativeControlAuth cannot call this overload.
    [[nodiscard]] NativeAuthorizationDecision operator()(std::string_view principal,
        std::string_view permission, std::string_view camera_id) const noexcept;
    // Bound native sessions use a separate internal endpoint. Both immutable
    // account ID and authentication epoch must match the authoritative snapshot.
    [[nodiscard]] NativeAuthorizationDecision operator()(std::string_view principal,
        const SessionIdentity &identity, std::string_view permission,
        std::string_view camera_id) const noexcept;

private:
    [[nodiscard]] NativeAuthorizationDecision request(std::string_view principal,
        const SessionIdentity *identity, std::string_view permission,
        std::string_view camera_id) const noexcept;
    NativeClusterAuthorizationConfig config_;
    // Copies share only our curl_global_init reference, never an easy handle.
    std::shared_ptr<void> runtime_;
};

} // namespace webobs
