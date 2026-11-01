#pragma once

#include "webobs/authentication.hpp"

#include <functional>
#include <string>
#include <string_view>

namespace webobs {

// Deliberately not a general permission string supplied by an untrusted caller.
// This boundary has no media, HTTP, login, Basic authentication or OBS dependency.
enum class NativeControlCommand {
    read_scene,
    write_scene,
    view_camera,
};

enum class NativeAuthorizationDecision {
    allowed,
    unknown_user, // Includes a disabled/deleted account; revoke every local session.
    denied,
    unavailable,
};

// The trusted adapter must perform a FRESH authoritative RBAC/scope lookup for
// every call, with a bounded deadline, and map malformed replies to unavailable.
// The callback must not accept the session cookie as its internal-service token.
// Arguments are borrowed only for the duration of the callback.
using NativeAuthorizationBackend = std::function<NativeAuthorizationDecision(
    std::string_view principal, std::string_view permission, std::string_view camera_id)>;

struct NativeControlAuthConfig {
    // Exact, canonical loopback HTTP(S) origin and authority (including any port).
    // Examples: http://127.0.0.1:8080 + 127.0.0.1:8080, https://[::1]:8443 + [::1]:8443.
    // No wildcard, userinfo, path, query, fragment, percent escape or DNS lookup.
    std::string origin;
    std::string authority;
};

struct NativeControlRequest {
    // Trusted transport metadata: peer_address MUST come from the socket/IPC
    // endpoint, never X-Forwarded-For or a caller-supplied identity/header.
    // An eventual HTTP adapter must reject duplicate/folded Origin/Host/cookie
    // fields before constructing this request; this is not an HTTP parser.
    std::string_view peer_address;
    std::string_view origin;
    std::string_view authority;
    std::string_view session_token; // Raw SessionStore token, not a Cookie header.
    NativeControlCommand command = NativeControlCommand::read_scene;
    // Optional for scene operations, mandatory for view_camera. Exactly one
    // existing camera ID, never a URL/path/list; scope is forwarded unchanged.
    std::string_view camera_id;
};

enum class NativeControlStatus {
    allowed = 200,
    invalid_request = 400,
    unauthenticated = 401,
    forbidden = 403,
    unavailable = 503,
};

struct NativeControlAuthorization {
    NativeControlStatus status = NativeControlStatus::unavailable;
    // Present ONLY on success. Never include raw credentials in diagnostics.
    std::string principal;

    [[nodiscard]] bool allowed() const noexcept { return status == NativeControlStatus::allowed; }
    [[nodiscard]] int status_code() const noexcept { return static_cast<int>(status); }
    [[nodiscard]] std::string_view code() const noexcept;
};

class NativeControlAuth {
public:
    // The owner must initialize the existing SessionStore successfully before
    // exposing commands, and keep it alive longer than this boundary. No login,
    // session creation, authority service or transport is implemented here.
    NativeControlAuth(SessionStore &sessions, NativeControlAuthConfig config,
                      NativeAuthorizationBackend backend);

    // No cached grants. A local session check alone can NEVER return allowed.
    // Run the corresponding allowlisted action immediately in the trusted
    // adapter; this result is not a transferable/reusable authorization token.
    [[nodiscard]] NativeControlAuthorization authorize(const NativeControlRequest &request) const;
    [[nodiscard]] bool configured() const noexcept { return configured_; }

private:
    SessionStore &sessions_;
    NativeControlAuthConfig config_;
    NativeAuthorizationBackend backend_;
    bool configured_ = false;
};

} // namespace webobs

/* Boundary only: production integration still needs a trusted, authenticated
 * cluster-service callback, bounded transport, private per-user session storage,
 * lifecycle ownership, and interception of every relevant OBS frontend action.
 * Merely adding this library does not authenticate the native OBS application.
 */
