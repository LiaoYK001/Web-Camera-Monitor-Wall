#include "webobs/studio_store.hpp"

#include <array>
#include <atomic>
#include <cerrno>
#include <cstring>
#include <string_view>
#include <system_error>
#include <utility>

#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace webobs {
namespace {

class FileDescriptor {
public:
    explicit FileDescriptor(int value = -1) : value_(value) {}
    FileDescriptor(const FileDescriptor &) = delete;
    FileDescriptor &operator=(const FileDescriptor &) = delete;
    FileDescriptor(FileDescriptor &&other) noexcept : value_(std::exchange(other.value_, -1)) {}
    FileDescriptor &operator=(FileDescriptor &&other) noexcept
    {
        if (this != &other) {
            if (value_ >= 0)
                close(value_);
            value_ = std::exchange(other.value_, -1);
        }
        return *this;
    }
    ~FileDescriptor()
    {
        if (value_ >= 0)
            close(value_);
    }
    [[nodiscard]] int get() const { return value_; }
    [[nodiscard]] explicit operator bool() const { return value_ >= 0; }
    bool close_checked()
    {
        const int value = std::exchange(value_, -1);
        return value < 0 || close(value) == 0;
    }

private:
    int value_;
};

struct Directory {
    FileDescriptor fd;
    std::string name;
    std::string error;
};

std::string system_error(std::string_view action)
{
    return std::string(action) + " failed: " + std::strerror(errno);
}

Directory open_directory(const std::filesystem::path &path, bool create)
{
    Directory result;
    if (!path.is_absolute() || path.filename().empty() || path.parent_path().empty()) {
        result.error = "studio file path must be absolute and include a filename";
        return result;
    }
    if (create) {
        std::error_code error;
        std::filesystem::create_directories(path.parent_path(), error);
        if (error) {
            result.error = "could not create the studio storage directory";
            return result;
        }
    }
    result.fd = FileDescriptor(open(path.parent_path().c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW));
    if (!result.fd) {
        result.error = system_error("opening the studio storage directory");
        return result;
    }
    struct stat metadata {};
    if (fstat(result.fd.get(), &metadata) != 0 || !S_ISDIR(metadata.st_mode) ||
        metadata.st_uid != geteuid()) {
        result.error = "studio storage directory must be an owned real directory";
        return result;
    }
    if (fchmod(result.fd.get(), S_IRWXU) != 0) {
        result.error = system_error("restricting the studio storage directory");
        return result;
    }
    result.name = path.filename().string();
    return result;
}

std::optional<std::string> validate_target(int directory, const std::string &name)
{
    struct stat metadata {};
    if (fstatat(directory, name.c_str(), &metadata, AT_SYMLINK_NOFOLLOW) != 0) {
        if (errno == ENOENT)
            return std::nullopt;
        return system_error("inspecting the existing studio file");
    }
    if (!S_ISREG(metadata.st_mode) || metadata.st_uid != geteuid() || metadata.st_nlink != 1)
        return "existing studio path must be an owned regular file without additional hard links";
    return std::nullopt;
}

bool write_all(int descriptor, std::string_view content)
{
    std::size_t offset = 0;
    while (offset < content.size()) {
        const ssize_t count = write(descriptor, content.data() + offset, content.size() - offset);
        if (count < 0 && errno == EINTR)
            continue;
        if (count <= 0)
            return false;
        offset += static_cast<std::size_t>(count);
    }
    return true;
}

std::optional<std::string> write_private_json(const std::filesystem::path &path, std::string_view content)
{
    Directory directory = open_directory(path, true);
    if (!directory.error.empty())
        return directory.error;
    if (const auto target_error = validate_target(directory.fd.get(), directory.name))
        return target_error;
    static std::atomic_uint64_t sequence = 0;
    const std::string temporary = "." + directory.name + ".tmp." +
                                  std::to_string(static_cast<long long>(getpid())) + "." +
                                  std::to_string(sequence.fetch_add(1));
    FileDescriptor file(openat(directory.fd.get(), temporary.c_str(),
                               O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW,
                               S_IRUSR | S_IWUSR));
    if (!file)
        return system_error("creating a temporary studio file");
    const auto cleanup = [&] { unlinkat(directory.fd.get(), temporary.c_str(), 0); };
    if (fchmod(file.get(), S_IRUSR | S_IWUSR) != 0 || !write_all(file.get(), content) ||
        fsync(file.get()) != 0 || !file.close_checked()) {
        const std::string error = system_error("writing the temporary studio file");
        cleanup();
        return error;
    }
    if (renameat(directory.fd.get(), temporary.c_str(), directory.fd.get(), directory.name.c_str()) != 0) {
        const std::string error = system_error("committing the studio file");
        cleanup();
        return error;
    }
    if (fsync(directory.fd.get()) != 0)
        return system_error("synchronizing the studio storage directory");
    return std::nullopt;
}

struct ReadResult {
    bool missing = false;
    std::string content;
    std::string error;
};

ReadResult read_private_json(const std::filesystem::path &path)
{
    ReadResult result;
    Directory directory = open_directory(path, false);
    if (!directory.error.empty()) {
        if (errno == ENOENT) {
            result.missing = true;
            return result;
        }
        result.error = directory.error;
        return result;
    }
    FileDescriptor file(openat(directory.fd.get(), directory.name.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW));
    if (!file) {
        if (errno == ENOENT) {
            result.missing = true;
            return result;
        }
        result.error = system_error("opening the studio file");
        return result;
    }
    struct stat metadata {};
    if (fstat(file.get(), &metadata) != 0 || !S_ISREG(metadata.st_mode) ||
        metadata.st_uid != geteuid() || metadata.st_nlink != 1) {
        result.error = "studio path must be an owned regular file without additional hard links";
        return result;
    }
    if (metadata.st_size < 0 || static_cast<std::uintmax_t>(metadata.st_size) > maximum_scene_json_bytes) {
        result.error = "studio file exceeds the one MiB limit";
        return result;
    }
    if (fchmod(file.get(), S_IRUSR | S_IWUSR) != 0) {
        result.error = system_error("restricting the studio file");
        return result;
    }
    std::array<char, 16384> buffer{};
    while (true) {
        const ssize_t count = read(file.get(), buffer.data(), buffer.size());
        if (count < 0 && errno == EINTR)
            continue;
        if (count < 0) {
            result.error = system_error("reading the studio file");
            return result;
        }
        if (count == 0)
            return result;
        if (result.content.size() + static_cast<std::size_t>(count) > maximum_scene_json_bytes) {
            result.error = "studio file exceeds the one MiB limit";
            return result;
        }
        result.content.append(buffer.data(), static_cast<std::size_t>(count));
    }
}

std::filesystem::path backup_path(const std::filesystem::path &path)
{
    return std::filesystem::path(path.string() + ".backup");
}

} // namespace

std::filesystem::path default_studio_path(const std::filesystem::path &scene_path)
{
    return scene_path.parent_path() / "studio.json";
}

std::optional<std::string> save_studio_file_atomic(const std::filesystem::path &path,
                                                   const StudioDocument &document,
                                                   bool preserve_backup)
{
    const SceneSerializeResult encoded =
        serialize_studio_json(document, SceneJsonView::persistence, true);
    if (!encoded.ok())
        return encoded.error;
    if (preserve_backup) {
        const ReadResult current = read_private_json(path);
        if (!current.error.empty())
            return current.error;
        if (!current.missing) {
            const StudioParseResult parsed = parse_studio_json(current.content);
            if (!parsed.ok())
                return "existing studio file is invalid; refusing to replace it without recovery";
            if (const auto backup_error = write_private_json(backup_path(path), current.content))
                return "could not preserve the previous studio revision: " + *backup_error;
        }
    }
    return write_private_json(path, encoded.json);
}

StudioFileLoadResult load_studio_file(const std::filesystem::path &path)
{
    StudioFileLoadResult result;
    const ReadResult primary = read_private_json(path);
    if (primary.missing) {
        result.status = StudioFileStatus::not_found;
        return result;
    }
    if (primary.error.empty()) {
        StudioParseResult parsed = parse_studio_json(primary.content);
        if (parsed.ok()) {
            result.status = StudioFileStatus::loaded;
            result.document = std::move(parsed.document);
            return result;
        }
    }

    const ReadResult backup = read_private_json(backup_path(path));
    if (!backup.error.empty() || backup.missing) {
        result.error = primary.error.empty() ? "studio file is invalid and no valid backup is available"
                                             : primary.error;
        return result;
    }
    StudioParseResult recovered = parse_studio_json(backup.content);
    if (!recovered.ok()) {
        result.error = "studio file and its backup are both invalid";
        return result;
    }
    if (const auto restore_error = write_private_json(path, backup.content)) {
        result.error = "studio backup is valid but could not be restored: " + *restore_error;
        return result;
    }
    result.status = StudioFileStatus::recovered_from_backup;
    result.document = std::move(recovered.document);
    return result;
}

} // namespace webobs
