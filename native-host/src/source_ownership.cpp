#include "source_ownership.hpp"

#include <algorithm>
#include <charconv>
#include <system_error>

namespace webobs::native_host {
namespace {

constexpr std::size_t kMaxLedgerBytes = 16 * 1024;
constexpr std::size_t kMaxEntries = 16;
constexpr std::size_t kMaxCameraIdLength = 64;

bool valid_camera_id(std::string_view id)
{
	if (id.empty() || id.size() > kMaxCameraIdLength)
		return false;
	auto ok = [](char c) {
		return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' ||
		       c == '_' || c == '.';
	};
	if (!ok(id[0]) || (id[0] == '-' || id[0] == '_' || id[0] == '.'))
		return false; // mirrors cluster IDENTIFIER: first char must be alphanumeric
	for (const char c : id.substr(1))
		if (!ok(c))
			return false;
	return true;
}

bool valid_source_uuid(std::string_view uuid)
{
	if (uuid.size() != 36)
		return false;
	for (std::size_t i = 0; i < 36; ++i) {
		if (i == 8 || i == 13 || i == 18 || i == 23) {
			if (uuid[i] != '-')
				return false;
			continue;
		}
		const char c = uuid[i];
		if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
			return false;
	}
	return true;
}

// Strict subset JSON scanner accepting exactly the ledger shape. Anything
// outside that shape (extra keys, escapes, floats, leading zeros, trailing
// content) is rejected rather than coerced.
class Parser {
public:
	explicit Parser(std::string_view text) : text_(text) {}

	bool parse_ledger(std::vector<OwnershipEntry> &out)
	{
		skip_space();
		if (!consume('{'))
			return false;
		if (!expect_key("schemaVersion"))
			return false;
		std::uint64_t version = 0;
		if (!parse_unsigned(version) || version != 1)
			return false;
		if (!consume(','))
			return false;
		if (!expect_key("entries"))
			return false;
		if (!consume('['))
			return false;
		skip_space();
		if (peek() == ']')
			return false; // empty ledger is invalid
		while (true) {
			if (out.size() >= kMaxEntries)
				return false;
			OwnershipEntry entry;
			if (!parse_entry(entry))
				return false;
			out.push_back(std::move(entry));
			skip_space();
			if (consume(','))
				continue;
			if (consume(']'))
				break;
			return false;
		}
		skip_space();
		if (!consume('}'))
			return false;
		skip_space();
		return pos_ == text_.size();
	}

private:
	char peek() const { return pos_ < text_.size() ? text_[pos_] : '\0'; }
	bool consume(char c)
	{
		if (peek() != c)
			return false;
		++pos_;
		return true;
	}
	void skip_space()
	{
		while (pos_ < text_.size() && (text_[pos_] == ' ' || text_[pos_] == '\t' || text_[pos_] == '\n' ||
					      text_[pos_] == '\r'))
			++pos_;
	}
	bool parse_string(std::string &out)
	{
		if (!consume('"'))
			return false;
		out.clear();
		while (pos_ < text_.size()) {
			const char c = text_[pos_++];
			if (c == '"')
				return true;
			if (c == '\\')
				return false; // ledger values never escape; stay strict
			if (static_cast<unsigned char>(c) < 0x20)
				return false;
			out.push_back(c);
		}
		return false;
	}
	bool parse_unsigned(std::uint64_t &out)
	{
		const std::size_t start = pos_;
		if (start >= text_.size() || text_[start] < '0' || text_[start] > '9')
			return false;
		if (text_[start] == '0' && start + 1 < text_.size() && text_[start + 1] >= '0' &&
		    text_[start + 1] <= '9')
			return false; // no leading zeros
		std::size_t end = start;
		while (end < text_.size() && text_[end] >= '0' && text_[end] <= '9')
			++end;
		const std::from_chars_result res = std::from_chars(text_.data() + start, text_.data() + end, out);
		if (res.ec != std::errc{} || res.ptr != text_.data() + end)
			return false;
		pos_ = end;
		return true;
	}
	bool expect_key(std::string_view key)
	{
		skip_space();
		std::string got;
		if (!parse_string(got) || got != key)
			return false;
		skip_space();
		return consume(':');
	}
	bool parse_entry(OwnershipEntry &entry)
	{
		skip_space();
		if (!consume('{'))
			return false;
		if (!expect_key("cameraId"))
			return false;
		if (!parse_string(entry.camera_id) || !valid_camera_id(entry.camera_id))
			return false;
		if (!consume(','))
			return false;
		if (!expect_key("sourceUuid"))
			return false;
		if (!parse_string(entry.source_uuid) || !valid_source_uuid(entry.source_uuid))
			return false;
		if (!consume(','))
			return false;
		if (!expect_key("generation"))
			return false;
		if (!parse_unsigned(entry.generation) || entry.generation == 0)
			return false;
		skip_space();
		return consume('}');
	}

	std::string_view text_;
	std::size_t pos_ = 0;
};

bool ledger_consistent(const std::vector<OwnershipEntry> &ledger)
{
	// An empty ledger is a valid initial state (no claims); decoding an
	// empty array file is separately rejected by the parser.
	if (ledger.size() > kMaxEntries)
		return false;
	for (const OwnershipEntry &entry : ledger)
		if (!valid_camera_id(entry.camera_id) || !valid_source_uuid(entry.source_uuid) || entry.generation == 0)
			return false;
	for (std::size_t i = 0; i < ledger.size(); ++i) {
		for (std::size_t j = i + 1; j < ledger.size(); ++j) {
			if (ledger[i].source_uuid == ledger[j].source_uuid)
				return false; // one uuid, two claims (ABA)
			if (ledger[i].camera_id == ledger[j].camera_id)
				return false; // only the newest incarnation may be held
			if (ledger[i].generation == ledger[j].generation)
				return false; // generations must order incarnations
		}
	}
	return true;
}

} // namespace

std::string encode_ownership_ledger(const std::vector<OwnershipEntry> &entries)
{
	std::string out = "{\"schemaVersion\":1,\"entries\":[";
	for (std::size_t i = 0; i < entries.size(); ++i) {
		if (i != 0)
			out += ",";
		out += "{\"cameraId\":\"" + entries[i].camera_id + "\",\"sourceUuid\":\"" + entries[i].source_uuid +
		       "\",\"generation\":" + std::to_string(entries[i].generation) + "}";
	}
	out += "]}";
	return out;
}

OwnershipLedgerResult decode_ownership_ledger(std::string_view json) noexcept
{
	if (json.empty() || json.size() > kMaxLedgerBytes)
		return {};
	std::vector<OwnershipEntry> entries;
	Parser parser(json);
	if (!parser.parse_ledger(entries))
		return {};
	if (!ledger_consistent(entries))
		return {};
	return {OwnershipStatus::success, std::move(entries)};
}

OwnershipStatus record_created_source(std::vector<OwnershipEntry> &entries, std::string_view camera_id,
				      std::string_view source_uuid) noexcept
{
	if (!ledger_consistent(entries))
		return OwnershipStatus::ledger_invalid;
	if (!valid_camera_id(camera_id) || !valid_source_uuid(source_uuid))
		return OwnershipStatus::record_conflict;
	std::size_t camera_slot = entries.size();
	for (std::size_t i = 0; i < entries.size(); ++i) {
		if (entries[i].source_uuid == source_uuid) {
			if (entries[i].camera_id == camera_id)
				return OwnershipStatus::success; // already recorded, idempotent
			return OwnershipStatus::record_conflict; // uuid claimed by another camera
		}
		if (entries[i].camera_id == camera_id)
			camera_slot = i;
	}
	std::uint64_t generation = 0;
	for (const OwnershipEntry &entry : entries)
		generation = std::max(generation, entry.generation);
	if (camera_slot == entries.size()) {
		if (entries.size() >= kMaxEntries)
			return OwnershipStatus::record_conflict;
		entries.push_back({std::string(camera_id), std::string(source_uuid), generation + 1});
	} else {
		// New incarnation for this camera: replace and free the previous uuid.
		entries[camera_slot] = {std::string(camera_id), std::string(source_uuid), generation + 1};
	}
	return OwnershipStatus::success;
}

std::vector<OwnershipBinding> classify_wall_entries(const std::vector<OwnershipEntry> &ledger,
						    const std::vector<std::string> &snapshot_uuids) noexcept
{
	std::vector<OwnershipBinding> bindings(snapshot_uuids.size());
	if (!ledger_consistent(ledger))
		return bindings; // fail closed: every entry unbound
	for (std::size_t i = 0; i < snapshot_uuids.size(); ++i) {
		for (const OwnershipEntry &entry : ledger) {
			if (entry.source_uuid == snapshot_uuids[i]) {
				bindings[i].camera_id = entry.camera_id;
				break;
			}
		}
	}
	return bindings;
}

bool ownership_ledger_consistent(const std::vector<OwnershipEntry> &ledger) noexcept
{
	return ledger_consistent(ledger);
}

bool ownership_source_uuid_valid(std::string_view uuid) noexcept
{
	return valid_source_uuid(uuid);
}
} // namespace webobs::native_host
