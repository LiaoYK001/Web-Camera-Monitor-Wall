#include "webobs/native_control_auth.hpp"

#include <cstddef>
#include <utility>

namespace webobs {
namespace {

constexpr std::size_t maximum_authority_size = 128;
constexpr std::size_t maximum_origin_size = 256;
constexpr std::size_t maximum_peer_size = 45;
constexpr std::size_t maximum_identifier_size = 64;
constexpr std::size_t session_token_size = 64;

bool ascii_alphanumeric(char character)
{
    return (character >= 'a' && character <= 'z') ||
           (character >= 'A' && character <= 'Z') ||
           (character >= '0' && character <= '9');
}

// Same bounded identifier alphabet as the account/camera authority, not a URL.
bool safe_identifier(std::string_view value, std::size_t minimum_size = 1)
{
    if (value.size() < minimum_size || value.size() > maximum_identifier_size ||
        !ascii_alphanumeric(value.front()))
        return false;
    for (char character : value) {
        if (!ascii_alphanumeric(character) && character != '.' && character != '_' && character != '-')
            return false;
    }
    return true;
}

bool canonical_decimal(std::string_view value, unsigned int maximum, unsigned int &number)
{
    if (value.empty() || value.size() > 5 || (value.size() > 1 && value.front() == '0'))
        return false;
    number = 0;
    for (char character : value) {
        if (character < '0' || character > '9')
            return false;
        number = number * 10 + static_cast<unsigned int>(character - '0');
        if (number > maximum)
            return false;
    }
    return true;
}

bool ipv4_loopback(std::string_view address)
{
    // Strict dotted decimal only: no abbreviated/octal/integer IPv4 aliases.
    if (address.empty() || address.size() > 15)
        return false;
    for (unsigned int index = 0; index < 4; ++index) {
        const auto separator = address.find('.');
        if ((index < 3 && separator == std::string_view::npos) ||
            (index == 3 && separator != std::string_view::npos))
            return false;
        const auto component = index < 3 ? address.substr(0, separator) : address;
        unsigned int number = 0;
        if (!canonical_decimal(component, 255, number) || (index == 0 && number != 127))
            return false;
        if (index < 3)
            address.remove_prefix(separator + 1);
    }
    return true;
}

bool loopback_peer(std::string_view peer)
{
    return peer.size() <= maximum_peer_size && (peer == "::1" || ipv4_loopback(peer));
}

bool safe_authority(std::string_view authority)
{
    if (authority.empty() || authority.size() > maximum_authority_size)
        return false;
    std::string_view host;
    std::string_view port;
    bool has_port = false;
    if (authority.front() == '[') {
        if (authority.substr(0, 5) != "[::1]")
            return false;
        host = authority.substr(0, 5);
        if (authority.size() > 5) {
            if (authority[5] != ':')
                return false;
            has_port = true;
            port = authority.substr(6);
        }
    } else {
        const auto separator = authority.find(':');
        host = authority.substr(0, separator);
        if (separator != std::string_view::npos) {
            has_port = true;
            port = authority.substr(separator + 1);
        }
    }
    if (host != "localhost" && host != "[::1]" && !ipv4_loopback(host))
        return false;
    if (!has_port)
        return true;
    unsigned int number = 0;
    return canonical_decimal(port, 65535, number) && number != 0;
}

bool safe_origin(std::string_view origin, std::string_view authority)
{
    if (origin.empty() || origin.size() > maximum_origin_size || !safe_authority(authority))
        return false;
    constexpr std::string_view http = "http://";
    constexpr std::string_view https = "https://";
    if (origin.substr(0, http.size()) == http)
        return origin.substr(http.size()) == authority;
    if (origin.substr(0, https.size()) == https)
        return origin.substr(https.size()) == authority;
    return false;
}

bool safe_session_token(std::string_view token)
{
    if (token.size() != session_token_size)
        return false;
    for (char character : token) {
        if ((character < '0' || character > '9') && (character < 'a' || character > 'f'))
            return false;
    }
    return true;
}

std::string_view permission_for_command(NativeControlCommand command)
{
    switch (command) {
    case NativeControlCommand::read_scene:
        return "scene.read";
    case NativeControlCommand::write_scene:
        return "scene.write";
    case NativeControlCommand::view_camera:
        return "live.view";
    }
    return {};
}

NativeControlAuthorization result(NativeControlStatus status)
{
    return {status, {}};
}

} // namespace

std::string_view NativeControlAuthorization::code() const noexcept
{
    switch (status) {
    case NativeControlStatus::allowed:
        return "allowed";
    case NativeControlStatus::invalid_request:
        return "invalid_request";
    case NativeControlStatus::unauthenticated:
        return "authentication_required";
    case NativeControlStatus::forbidden:
        return "forbidden";
    case NativeControlStatus::unavailable:
        return "authorization_unavailable";
    }
    return "authorization_unavailable";
}

NativeControlAuth::NativeControlAuth(SessionStore &sessions, NativeControlAuthConfig config,
                                   NativeAuthorizationBackend backend)
    : sessions_(sessions), config_(std::move(config)), backend_(std::move(backend))
{
    configured_ = sessions_.enabled() && static_cast<bool>(backend_) &&
                  safe_origin(config_.origin, config_.authority);
}

NativeControlAuthorization NativeControlAuth::authorize(const NativeControlRequest &request) const
{
    if (!configured_)
        return result(NativeControlStatus::unavailable);

    // Validate all caller-controlled structure before touching sessions/backend.
    // Compare exact configured values, never a permissive localhost substring.
    if (!loopback_peer(request.peer_address))
        return result(NativeControlStatus::forbidden);
    if (!safe_authority(request.authority) || !safe_origin(request.origin, request.authority) ||
        request.authority != config_.authority || request.origin != config_.origin)
        return result(NativeControlStatus::forbidden);
    const auto permission = permission_for_command(request.command);
    if (permission.empty() ||
        (!request.camera_id.empty() && !safe_identifier(request.camera_id)) ||
        (request.command == NativeControlCommand::view_camera && request.camera_id.empty()) ||
        request.session_token.size() > session_token_size)
        return result(NativeControlStatus::invalid_request);
    if (!safe_session_token(request.session_token))
        return result(NativeControlStatus::unauthenticated);

    try {
        const auto session = sessions_.validate_and_slide(request.session_token);
        if (!session || !safe_identifier(session->user, 3))
            return result(NativeControlStatus::unauthenticated);
        const auto decision = backend_(session->user, permission, request.camera_id);
        switch (decision) {
        case NativeAuthorizationDecision::allowed: {
            // A logout/revocation while the backend was in flight must not grant
            // a command using the formerly valid session.
            const auto current = sessions_.validate_and_slide(request.session_token);
            if (!current || current->user != session->user)
                return result(NativeControlStatus::unauthenticated);
            return {NativeControlStatus::allowed, session->user};
        }
        case NativeAuthorizationDecision::unknown_user:
            // SessionStore reports both DELETE failure and zero matching rows
            // as zero. Do not claim revocation succeeded while tokens remain.
            // Concurrent prior revocation can conservatively return 503 too.
            if (sessions_.revoke_user(session->user) == 0)
                return result(NativeControlStatus::unavailable);
            return result(NativeControlStatus::unauthenticated);
        case NativeAuthorizationDecision::denied:
            return result(NativeControlStatus::forbidden);
        case NativeAuthorizationDecision::unavailable:
            return result(NativeControlStatus::unavailable);
        }
        // Defensive against an invalid enum from an incomplete adapter.
        return result(NativeControlStatus::unavailable);
    } catch (...) {
        // Do not relay exception messages: they can contain credentials/URLs.
        return result(NativeControlStatus::unavailable);
    }
}

} // namespace webobs
