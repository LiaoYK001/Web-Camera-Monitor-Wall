#include "webobs/authentication.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <vector>

namespace webobs {
namespace {

constexpr std::size_t maximum_tracked_clients = 1024;
constexpr std::size_t maximum_credential_size = 256;

int base64_value(unsigned char character)
{
    if (character >= 'A' && character <= 'Z')
        return character - 'A';
    if (character >= 'a' && character <= 'z')
        return character - 'a' + 26;
    if (character >= '0' && character <= '9')
        return character - '0' + 52;
    if (character == '+')
        return 62;
    if (character == '/')
        return 63;
    return -1;
}

std::optional<std::string> decode_base64(std::string_view encoded)
{
    if (encoded.empty() || encoded.size() > 1024 || encoded.size() % 4 != 0)
        return std::nullopt;
    std::string decoded;
    decoded.reserve((encoded.size() / 4) * 3);
    for (std::size_t offset = 0; offset < encoded.size(); offset += 4) {
        const bool final_block = offset + 4 == encoded.size();
        const bool third_padding = encoded[offset + 2] == '=';
        const bool fourth_padding = encoded[offset + 3] == '=';
        if ((!final_block && (third_padding || fourth_padding)) || (third_padding && !fourth_padding))
            return std::nullopt;
        const int first = base64_value(static_cast<unsigned char>(encoded[offset]));
        const int second = base64_value(static_cast<unsigned char>(encoded[offset + 1]));
        const int third = third_padding ? 0 : base64_value(static_cast<unsigned char>(encoded[offset + 2]));
        const int fourth = fourth_padding ? 0 : base64_value(static_cast<unsigned char>(encoded[offset + 3]));
        if (first < 0 || second < 0 || third < 0 || fourth < 0)
            return std::nullopt;
        if ((third_padding && (second & 0x0f) != 0) ||
            (fourth_padding && !third_padding && (third & 0x03) != 0))
            return std::nullopt;
        const unsigned int value = static_cast<unsigned int>((first << 18) | (second << 12) |
                                                              (third << 6) | fourth);
        decoded.push_back(static_cast<char>((value >> 16) & 0xff));
        if (!third_padding)
            decoded.push_back(static_cast<char>((value >> 8) & 0xff));
        if (!fourth_padding)
            decoded.push_back(static_cast<char>(value & 0xff));
    }
    return decoded;
}

bool basic_prefix(std::string_view value)
{
    constexpr std::string_view prefix = "Basic ";
    if (value.size() < prefix.size())
        return false;
    for (std::size_t index = 0; index < prefix.size(); ++index) {
        unsigned char actual = static_cast<unsigned char>(value[index]);
        unsigned char expected = static_cast<unsigned char>(prefix[index]);
        if (actual >= 'A' && actual <= 'Z')
            actual = static_cast<unsigned char>(actual - 'A' + 'a');
        if (expected >= 'A' && expected <= 'Z')
            expected = static_cast<unsigned char>(expected - 'A' + 'a');
        if (actual != expected)
            return false;
    }
    return true;
}

bool constant_time_equal(std::string_view left, std::string_view right)
{
    std::array<unsigned char, maximum_credential_size> left_bytes{};
    std::array<unsigned char, maximum_credential_size> right_bytes{};
    const std::size_t left_size = std::min(left.size(), left_bytes.size());
    const std::size_t right_size = std::min(right.size(), right_bytes.size());
    std::copy_n(reinterpret_cast<const unsigned char *>(left.data()), left_size, left_bytes.begin());
    std::copy_n(reinterpret_cast<const unsigned char *>(right.data()), right_size, right_bytes.begin());
    std::size_t difference = left.size() ^ right.size();
    for (std::size_t index = 0; index < left_bytes.size(); ++index)
        difference |= left_bytes[index] ^ right_bytes[index];
    return difference == 0 && left.size() <= left_bytes.size() && right.size() <= right_bytes.size();
}

} // namespace

BasicAuthenticator::BasicAuthenticator(std::optional<BasicAuthCredentials> credentials,
                                       std::size_t failure_limit,
                                       std::chrono::seconds failure_window)
    : credentials_(std::move(credentials)), failure_limit_(failure_limit), failure_window_(failure_window)
{
}

AuthenticationDecision BasicAuthenticator::authenticate(
    std::optional<std::string_view> authorization, std::string_view client_key,
    std::chrono::steady_clock::time_point now)
{
    if (!credentials_)
        return AuthenticationDecision::allowed;
    prune(now);
    const auto existing = failures_.find(std::string(client_key));
    if (existing != failures_.end() && existing->second.failures >= failure_limit_)
        return AuthenticationDecision::rate_limited;
    if (!authorization)
        return AuthenticationDecision::credentials_required;
    if (credentials_match(*authorization)) {
        if (existing != failures_.end())
            failures_.erase(existing);
        return AuthenticationDecision::allowed;
    }

    ++failed_attempts_;
    auto entry = failures_.find(std::string(client_key));
    if (entry == failures_.end()) {
        if (failures_.size() >= maximum_tracked_clients)
            return AuthenticationDecision::rate_limited;
        entry = failures_.emplace(std::string(client_key), FailureWindow{now, 0}).first;
    }
    ++entry->second.failures;
    return entry->second.failures >= failure_limit_ ? AuthenticationDecision::rate_limit_started
                                                    : AuthenticationDecision::invalid_credentials;
}

std::size_t BasicAuthenticator::retry_after_seconds() const
{
    const auto seconds = failure_window_.count();
    if (seconds <= 0)
        return 1;
    return static_cast<std::size_t>(std::min<std::int64_t>(seconds, std::numeric_limits<int>::max()));
}

bool BasicAuthenticator::credentials_match(std::string_view authorization) const
{
    if (!credentials_ || !basic_prefix(authorization))
        return false;
    const auto decoded = decode_base64(authorization.substr(6));
    if (!decoded)
        return false;
    const std::size_t separator = decoded->find(':');
    if (separator == std::string::npos)
        return false;
    return constant_time_equal(std::string_view(*decoded).substr(0, separator), credentials_->username) &
           constant_time_equal(std::string_view(*decoded).substr(separator + 1), credentials_->password);
}

void BasicAuthenticator::prune(std::chrono::steady_clock::time_point now)
{
    for (auto iterator = failures_.begin(); iterator != failures_.end();) {
        if (now - iterator->second.started >= failure_window_)
            iterator = failures_.erase(iterator);
        else
            ++iterator;
    }
}

} // namespace webobs
