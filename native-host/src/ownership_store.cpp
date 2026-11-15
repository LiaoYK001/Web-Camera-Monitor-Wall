#include "ownership_store.hpp"

#include <cstddef>
#include <cstdio>
#include <string>

#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#include <sys/stat.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

namespace webobs::native_host {
namespace {
constexpr std::size_t kMaxFileBytes = 16384;

#if defined(_WIN32)
constexpr int kOpenRead = _O_RDONLY | _O_BINARY;
constexpr int kOpenWrite = _O_WRONLY | _O_CREAT | _O_TRUNC | _O_BINARY;
constexpr int kCreateMode = _S_IREAD | _S_IWRITE;
int open_file(const std::string &path, int flags)
{
	return _open(path.c_str(), flags, kCreateMode);
}
long read_file(int fd, char *buffer, std::size_t size)
{
	const int read = _read(fd, buffer, unsigned(size > 512u ? 512u : size));
	return read < 0 ? -1L : long(read);
}
long write_file(int fd, const char *buffer, std::size_t size)
{
	const int written = _write(fd, buffer, unsigned(size > 512u ? 512u : size));
	return written < 0 ? -1L : long(written);
}
void close_file(int fd) { _close(fd); }
void remove_file(const std::string &path) { _unlink(path.c_str()); }
#else
constexpr int kOpenRead = O_RDONLY;
constexpr int kOpenWrite = O_WRONLY | O_CREAT | O_TRUNC;
constexpr mode_t kCreateMode = 0600;
int open_file(const std::string &path, int flags)
{
	return open(path.c_str(), flags, kCreateMode);
}
long read_file(int fd, char *buffer, std::size_t size)
{
	const ssize_t read = ::read(fd, buffer, size);
	return read < 0 ? -1L : long(read);
}
long write_file(int fd, const char *buffer, std::size_t size)
{
	const ssize_t written = ::write(fd, buffer, size);
	return written < 0 ? -1L : long(written);
}
void close_file(int fd) { ::close(fd); }
void remove_file(const std::string &path) { ::unlink(path.c_str()); }
#endif
} // namespace

OwnershipStoreResult load_ownership_store(const std::string &path) noexcept
{
	OwnershipStoreResult result;
	const int fd = open_file(path, kOpenRead);
	if (fd < 0) {
		result.status = OwnershipStoreStatus::absent;
		return result;
	}
	std::string bytes;
	char buffer[512];
	for (;;) {
		const long read = read_file(fd, buffer, sizeof(buffer));
		if (read < 0) {
			close_file(fd);
			result.status = OwnershipStoreStatus::io_error;
			return result;
		}
		if (read == 0)
			break;
		bytes.append(buffer, std::size_t(read));
		if (bytes.size() > kMaxFileBytes) {
			close_file(fd);
			result.status = OwnershipStoreStatus::invalid_ledger;
			return result;
		}
	}
	close_file(fd);
	const OwnershipLedgerResult decoded = decode_ownership_ledger(bytes);
	if (decoded.status != OwnershipStatus::success || !decoded.entries) {
		result.status = OwnershipStoreStatus::invalid_ledger;
		return result;
	}
	result.status = OwnershipStoreStatus::success;
	result.entries = *decoded.entries;
	return result;
}

OwnershipStoreStatus save_ownership_store(const std::string &path,
					  const std::vector<OwnershipEntry> &entries) noexcept
{
	// Round-trip through the strict decoder first: an inconsistent ledger is
	// refused before any write, so existing content stays untouched.
	const std::string encoded = encode_ownership_ledger(entries);
	if (decode_ownership_ledger(encoded).status != OwnershipStatus::success) {
		return OwnershipStoreStatus::invalid_ledger;
	}
	const std::string temp = path + ".tmp";
	const int fd = open_file(temp, kOpenWrite);
	if (fd < 0) {
		return OwnershipStoreStatus::io_error;
	}
	std::size_t written_total = 0;
	bool io_ok = true;
	while (written_total < encoded.size()) {
		const long written = write_file(fd, encoded.data() + written_total,
						encoded.size() - written_total);
		if (written <= 0) {
			io_ok = false;
			break;
		}
		written_total += std::size_t(written);
	}
	close_file(fd);
	if (!io_ok || written_total != encoded.size()) {
		remove_file(temp);
		return OwnershipStoreStatus::io_error;
	}
	// POSIX rename replaces atomically. Windows rename does not replace an
	// existing target, so the previous file is removed first; a crash between
	// remove and rename can lose the ledger (documented, not repaired).
	if (std::rename(temp.c_str(), path.c_str()) != 0) {
		remove_file(path);
		if (std::rename(temp.c_str(), path.c_str()) != 0) {
			remove_file(temp);
			return OwnershipStoreStatus::io_error;
		}
	}
	return OwnershipStoreStatus::success;
}
} // namespace webobs::native_host
