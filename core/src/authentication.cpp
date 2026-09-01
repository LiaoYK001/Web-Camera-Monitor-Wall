#include "webobs/authentication.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <cctype>
#include <filesystem>
#include <memory>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <sqlite3.h>
#include <ctime>
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

AuthenticationDecision BasicAuthenticator::authenticate_plain(
    std::string_view username, std::string_view password, std::string_view client_key,
    std::chrono::steady_clock::time_point now)
{
    if (!credentials_)
        return AuthenticationDecision::credentials_required;
    prune(now);
    const auto existing = failures_.find(std::string(client_key));
    if (existing != failures_.end() && existing->second.failures >= failure_limit_)
        return AuthenticationDecision::rate_limited;
    if (credentials_match_plain(username, password)) {
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

bool BasicAuthenticator::credentials_match_plain(std::string_view username,
                                                 std::string_view password) const
{
    return credentials_ && constant_time_equal(username, credentials_->username) &
                               constant_time_equal(password, credentials_->password);
}

std::string_view BasicAuthenticator::configured_username() const
{
    return credentials_ ? std::string_view(credentials_->username) : std::string_view{};
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

struct SessionStore::Impl {
    sqlite3 *database = nullptr;
};

namespace {

std::string hex_encode(const unsigned char *bytes, std::size_t size)
{
    constexpr char hexadecimal[] = "0123456789abcdef";
    std::string result;
    result.reserve(size * 2);
    for (std::size_t index = 0; index < size; ++index) {
        result.push_back(hexadecimal[bytes[index] >> 4]);
        result.push_back(hexadecimal[bytes[index] & 0x0f]);
    }
    return result;
}

std::optional<std::string> session_hash(std::string_view token)
{
    if (token.size() != 64 || !std::all_of(token.begin(), token.end(), [](unsigned char character) {
            return std::isxdigit(character);
        }))
        return std::nullopt;
    unsigned char digest[EVP_MAX_MD_SIZE]{};
    unsigned int digest_size = 0;
    EVP_MD_CTX *context = EVP_MD_CTX_new();
    if (!context)
        return std::nullopt;
    const bool ok = EVP_DigestInit_ex(context, EVP_sha256(), nullptr) == 1 &&
                    EVP_DigestUpdate(context, token.data(), token.size()) == 1 &&
                    EVP_DigestFinal_ex(context, digest, &digest_size) == 1;
    EVP_MD_CTX_free(context);
    if (!ok)
        return std::nullopt;
    return hex_encode(digest, digest_size);
}

bool execute_sql(sqlite3 *database, const char *sql)
{
    char *message = nullptr;
    const int result = sqlite3_exec(database, sql, nullptr, nullptr, &message);
    sqlite3_free(message);
    return result == SQLITE_OK;
}

void prune_expired_sessions(sqlite3 *database, std::int64_t now)
{
    sqlite3_stmt *statement = nullptr;
    if (sqlite3_prepare_v2(database, "DELETE FROM auth_sessions WHERE expires_at<=?", -1,
                           &statement, nullptr) != SQLITE_OK)
        return;
    sqlite3_bind_int64(statement, 1, now);
    sqlite3_step(statement);
    sqlite3_finalize(statement);
}

} // namespace

SessionStore::SessionStore(std::string database_path, std::chrono::seconds inactivity_expiry,
                           bool secure_cookie)
    : database_path_(std::move(database_path)), inactivity_expiry_(inactivity_expiry),
      secure_cookie_(secure_cookie), impl_(std::make_unique<Impl>())
{
}

SessionStore::~SessionStore()
{
    if (impl_ && impl_->database)
        sqlite3_close(impl_->database);
}

std::optional<std::string> SessionStore::initialize()
{
    std::lock_guard lock(mutex_);
    if (!enabled() || impl_->database)
        return std::nullopt;
    std::error_code error;
    std::filesystem::create_directories(std::filesystem::path(database_path_).parent_path(), error);
    if (error)
        return "could not create the session database directory";
    if (sqlite3_open_v2(database_path_.c_str(), &impl_->database,
                        SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX,
                        nullptr) != SQLITE_OK) {
        if (impl_->database)
            sqlite3_close(impl_->database);
        impl_->database = nullptr;
        return "could not open the session database";
    }
    sqlite3_busy_timeout(impl_->database, 3000);
    if (!execute_sql(impl_->database, "PRAGMA journal_mode=WAL") ||
        !execute_sql(impl_->database, "PRAGMA synchronous=NORMAL") ||
        !execute_sql(impl_->database,
            "CREATE TABLE IF NOT EXISTS auth_sessions("
            "session_id_hash TEXT PRIMARY KEY,user_name TEXT NOT NULL,created_at INTEGER NOT NULL,"
            "last_seen INTEGER NOT NULL,expires_at INTEGER NOT NULL,client_metadata TEXT NOT NULL)") ||
        !execute_sql(impl_->database,
            "CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires_at)")) {
        sqlite3_close(impl_->database);
        impl_->database = nullptr;
        return "could not initialize the session database schema";
    }
    prune_expired_sessions(impl_->database, static_cast<std::int64_t>(std::time(nullptr)));
    return std::nullopt;
}

std::optional<std::string> SessionStore::create(std::string_view user,
                                               std::string_view client_metadata)
{
    std::lock_guard lock(mutex_);
    if (!impl_->database || user.empty() || user.size() > 64)
        return std::nullopt;
    std::array<unsigned char, 32> random_bytes{};
    if (RAND_bytes(random_bytes.data(), static_cast<int>(random_bytes.size())) != 1)
        return std::nullopt;
    const std::string token = hex_encode(random_bytes.data(), random_bytes.size());
    const auto hash = session_hash(token);
    if (!hash)
        return std::nullopt;
    const std::int64_t now = static_cast<std::int64_t>(std::time(nullptr));
    const std::int64_t expires = now + inactivity_expiry_.count();
    prune_expired_sessions(impl_->database, now);
    std::string metadata(client_metadata.substr(0, 256));
    sqlite3_stmt *statement = nullptr;
    const char *sql = "INSERT INTO auth_sessions(session_id_hash,user_name,created_at,last_seen,expires_at,client_metadata) VALUES(?,?,?,?,?,?)";
    if (sqlite3_prepare_v2(impl_->database, sql, -1, &statement, nullptr) != SQLITE_OK)
        return std::nullopt;
    sqlite3_bind_text(statement, 1, hash->c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 2, std::string(user).c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(statement, 3, now);
    sqlite3_bind_int64(statement, 4, now);
    sqlite3_bind_int64(statement, 5, expires);
    sqlite3_bind_text(statement, 6, metadata.c_str(), -1, SQLITE_TRANSIENT);
    const bool inserted = sqlite3_step(statement) == SQLITE_DONE;
    sqlite3_finalize(statement);
    return inserted ? std::optional<std::string>(token) : std::nullopt;
}

std::optional<SessionRecord> SessionStore::validate_and_slide(std::string_view token)
{
    const auto hash = session_hash(token);
    if (!hash)
        return std::nullopt;
    std::lock_guard lock(mutex_);
    if (!impl_->database)
        return std::nullopt;
    const std::int64_t now = static_cast<std::int64_t>(std::time(nullptr));
    const std::int64_t expires = now + inactivity_expiry_.count();
    sqlite3_stmt *update = nullptr;
    if (sqlite3_prepare_v2(impl_->database,
            "UPDATE auth_sessions SET last_seen=?,expires_at=? WHERE session_id_hash=? AND expires_at>?",
            -1, &update, nullptr) != SQLITE_OK)
        return std::nullopt;
    sqlite3_bind_int64(update, 1, now);
    sqlite3_bind_int64(update, 2, expires);
    sqlite3_bind_text(update, 3, hash->c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(update, 4, now);
    const bool updated = sqlite3_step(update) == SQLITE_DONE && sqlite3_changes(impl_->database) == 1;
    sqlite3_finalize(update);
    if (!updated)
        return std::nullopt;
    sqlite3_stmt *select = nullptr;
    if (sqlite3_prepare_v2(impl_->database,
            "SELECT user_name,created_at,last_seen,expires_at FROM auth_sessions WHERE session_id_hash=?",
            -1, &select, nullptr) != SQLITE_OK)
        return std::nullopt;
    sqlite3_bind_text(select, 1, hash->c_str(), -1, SQLITE_TRANSIENT);
    SessionRecord record;
    const bool found = sqlite3_step(select) == SQLITE_ROW;
    if (found) {
        record.user = reinterpret_cast<const char *>(sqlite3_column_text(select, 0));
        record.created_at = sqlite3_column_int64(select, 1);
        record.last_seen = sqlite3_column_int64(select, 2);
        record.expires_at = sqlite3_column_int64(select, 3);
    }
    sqlite3_finalize(select);
    return found ? std::optional<SessionRecord>(std::move(record)) : std::nullopt;
}

bool SessionStore::revoke(std::string_view token)
{
    const auto hash = session_hash(token);
    if (!hash)
        return false;
    std::lock_guard lock(mutex_);
    if (!impl_->database)
        return false;
    sqlite3_stmt *statement = nullptr;
    if (sqlite3_prepare_v2(impl_->database,
            "DELETE FROM auth_sessions WHERE session_id_hash=?", -1, &statement, nullptr) != SQLITE_OK)
        return false;
    sqlite3_bind_text(statement, 1, hash->c_str(), -1, SQLITE_TRANSIENT);
    const bool removed = sqlite3_step(statement) == SQLITE_DONE && sqlite3_changes(impl_->database) == 1;
    sqlite3_finalize(statement);
    return removed;
}

std::size_t SessionStore::revoke_user(std::string_view user)
{
    if (user.empty() || user.size() > 64)
        return 0;
    std::lock_guard lock(mutex_);
    if (!impl_->database)
        return 0;
    sqlite3_stmt *statement = nullptr;
    if (sqlite3_prepare_v2(impl_->database,
            "DELETE FROM auth_sessions WHERE user_name=?", -1, &statement, nullptr) != SQLITE_OK)
        return 0;
    sqlite3_bind_text(statement, 1, std::string(user).c_str(), -1, SQLITE_TRANSIENT);
    const bool deleted = sqlite3_step(statement) == SQLITE_DONE;
    const int changes = deleted ? sqlite3_changes(impl_->database) : 0;
    sqlite3_finalize(statement);
    return changes > 0 ? static_cast<std::size_t>(changes) : 0;
}

std::string SessionStore::set_cookie_header(std::string_view token) const
{
    return "webobs_session=" + std::string(token) + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=" +
           std::to_string(inactivity_expiry_.count()) + (secure_cookie_ ? "; Secure" : "");
}

std::string SessionStore::clear_cookie_header() const
{
    return "webobs_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" +
           std::string(secure_cookie_ ? "; Secure" : "");
}

} // namespace webobs
