#ifdef _WIN32
#include "webobs/platform_runtime.hpp"
#include <windows.h>
#include <aclapi.h>
#include <atomic>
#include <vector>

namespace webobs {
namespace {
struct Handle { HANDLE value = INVALID_HANDLE_VALUE; ~Handle() { if (value != INVALID_HANDLE_VALUE) CloseHandle(value); } };
std::vector<unsigned char> user_token() {
    Handle token;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.value)) return {};
    DWORD length = 0; GetTokenInformation(token.value, TokenUser, nullptr, 0, &length);
    std::vector<unsigned char> data(length);
    if (!GetTokenInformation(token.value, TokenUser, data.data(), length, &length)) return {};
    return data;
}
bool owned_regular(HANDLE handle, bool directory) {
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(handle, &info) || (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) ||
        bool(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != directory || (!directory && info.nNumberOfLinks != 1)) return false;
    PSID owner = nullptr; PSECURITY_DESCRIPTOR security = nullptr;
    const auto token = user_token();
    if (token.empty() || GetSecurityInfo(handle, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION, &owner, nullptr, nullptr, nullptr, &security) != ERROR_SUCCESS) return false;
    const bool same = EqualSid(owner, reinterpret_cast<const TOKEN_USER*>(token.data())->User.Sid);
    LocalFree(security); return same;
}
bool restrict_handle(HANDLE handle, bool directory) {
    const auto token = user_token(); if (token.empty()) return false;
    EXPLICIT_ACCESSW access{}; access.grfAccessPermissions = GENERIC_ALL; access.grfAccessMode = SET_ACCESS;
    access.grfInheritance = directory ? SUB_CONTAINERS_AND_OBJECTS_INHERIT : NO_INHERITANCE;
    access.Trustee.TrusteeForm = TRUSTEE_IS_SID; access.Trustee.TrusteeType = TRUSTEE_IS_USER;
    access.Trustee.ptstrName = reinterpret_cast<LPWSTR>(reinterpret_cast<const TOKEN_USER*>(token.data())->User.Sid);
    PACL acl = nullptr;
    if (SetEntriesInAclW(1, &access, nullptr, &acl) != ERROR_SUCCESS) return false;
    const DWORD status = SetSecurityInfo(handle, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION|PROTECTED_DACL_SECURITY_INFORMATION, nullptr, nullptr, acl, nullptr);
    LocalFree(acl); return status == ERROR_SUCCESS;
}
std::optional<std::string> parent(const std::filesystem::path& path, bool create) {
    if (!path.is_absolute() || path.filename().empty() || path.parent_path().empty()) return "storage path must be absolute";
    std::error_code error;
    if (create) std::filesystem::create_directories(path.parent_path(), error);
    if (error) return "could not create private storage";
    for (auto check = path.parent_path(); !check.empty() && check != check.root_path(); check = check.parent_path()) {
        const DWORD attributes = GetFileAttributesW(check.c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES) return "storage directory unavailable";
        if (attributes & FILE_ATTRIBUTE_REPARSE_POINT) return "reparse points are forbidden in private storage";
    }
    Handle directory{CreateFileW(path.parent_path().c_str(), READ_CONTROL|WRITE_DAC|FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT, nullptr)};
    if (directory.value == INVALID_HANDLE_VALUE || !owned_regular(directory.value, true) || !restrict_handle(directory.value, true)) return "private storage must be owned by the current Windows user";
    return {};
}
}
PrivateRead windows_private_read(const std::filesystem::path& path, std::size_t limit) {
    PrivateRead result;
    if (GetFileAttributesW(path.parent_path().c_str()) == INVALID_FILE_ATTRIBUTES && GetLastError() == ERROR_PATH_NOT_FOUND) { result.missing = true; return result; }
    if (const auto error = parent(path, false)) {
        if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES && (GetLastError() == ERROR_FILE_NOT_FOUND || GetLastError() == ERROR_PATH_NOT_FOUND)) result.missing = true;
        else result.error = *error;
        return result;
    }
    Handle file{CreateFileW(path.c_str(), GENERIC_READ|READ_CONTROL|WRITE_DAC, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr)};
    if (file.value == INVALID_HANDLE_VALUE) { result.missing = GetLastError() == ERROR_FILE_NOT_FOUND; if (!result.missing) result.error = "private file unavailable"; return result; }
    if (!owned_regular(file.value, false) || !restrict_handle(file.value, false)) { result.error = "private file must be owned, regular and singly linked"; return result; }
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file.value, &size) || size.QuadPart < 0 || static_cast<unsigned long long>(size.QuadPart) > limit) { result.error = "private file exceeds size limit"; return result; }
    result.content.resize(static_cast<std::size_t>(size.QuadPart)); DWORD count = 0;
    if (!ReadFile(file.value, result.content.data(), static_cast<DWORD>(result.content.size()), &count, nullptr) || count != result.content.size()) result.error = "private file read failed";
    return result;
}
std::optional<std::string> windows_private_write(const std::filesystem::path& path, std::string_view content) {
    if (content.size() > 1024*1024) return "private file exceeds one MiB limit";
    if (const auto error = parent(path, true)) return error;
    const auto current = windows_private_read(path, 1024*1024);
    if (!current.error.empty()) return current.error;
    static std::atomic_uint64_t serial = 0;
    const auto temporary = path.parent_path() / (L".webobs-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(serial.fetch_add(1))+L".tmp");
    Handle file{CreateFileW(temporary.c_str(), GENERIC_WRITE|READ_CONTROL|WRITE_DAC, 0, nullptr, CREATE_NEW, FILE_FLAG_OPEN_REPARSE_POINT|FILE_FLAG_WRITE_THROUGH, nullptr)};
    if (file.value == INVALID_HANDLE_VALUE) return "private temporary file creation failed";
    DWORD written = 0;
    const bool ok = owned_regular(file.value, false) && restrict_handle(file.value, false) &&
        WriteFile(file.value, content.data(), static_cast<DWORD>(content.size()), &written, nullptr) && written == content.size() && FlushFileBuffers(file.value);
    CloseHandle(file.value); file.value = INVALID_HANDLE_VALUE;
    if (!ok || !MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) { DeleteFileW(temporary.c_str()); return "private atomic write failed"; }
    return {};
}
}
#endif
