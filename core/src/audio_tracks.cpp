#include "webobs/audio_tracks.hpp"

#include <cstddef>
#include <memory>

#include <jansson.h>

namespace webobs {
namespace {

constexpr std::size_t maximum_ffprobe_bytes = 1024 * 1024;
constexpr int maximum_audio_tracks = 32;

struct JsonDeleter {
    void operator()(json_t *value) const
    {
        if (value)
            json_decref(value);
    }
};

using JsonPtr = std::unique_ptr<json_t, JsonDeleter>;

bool lowercase_hex_token(std::string_view value)
{
    if (value.size() != 32)
        return false;
    for (const char character : value)
        if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f')))
            return false;
    return true;
}

bool route_path_with_prefix(std::string_view path, std::string_view prefix)
{
    return path.size() == prefix.size() + 32 && path.starts_with(prefix) &&
           lowercase_hex_token(path.substr(prefix.size()));
}

std::string string_field(json_t *object, const char *key)
{
    json_t *value = json_object_get(object, key);
    if (!json_is_string(value))
        return {};
    const char *text = json_string_value(value);
    return text ? std::string(text) : std::string{};
}

/**
 * ffprobe reports some numbers as JSON strings (for example `"sample_rate":
 * "16000"`), so both representations are accepted and everything else falls
 * back instead of inventing a value.
 */
int numeric_field(json_t *object, const char *key, int fallback)
{
    json_t *value = json_object_get(object, key);
    if (json_is_integer(value)) {
        const json_int_t number = json_integer_value(value);
        if (number < 0 || number > 1000000)
            return fallback;
        return static_cast<int>(number);
    }
    if (!json_is_string(value))
        return fallback;
    const char *text = json_string_value(value);
    if (!text || !*text)
        return fallback;
    int number = 0;
    for (const char *cursor = text; *cursor; ++cursor) {
        if (*cursor < '0' || *cursor > '9')
            return fallback;
        number = number * 10 + (*cursor - '0');
        if (number > 1000000)
            return fallback;
    }
    return number;
}

} // namespace

bool audio_track_browser_compatible(std::string_view codec)
{
    // Opus is the WebRTC baseline; G.711 passes through untouched.  Everything
    // else (AAC, HEVC/G.726, and so on) needs the audio-only Opus transcode.
    return codec == "opus" || codec == "pcm_alaw" || codec == "pcm_mulaw";
}

std::vector<AudioTrackDescriptor> parse_audio_tracks(std::string_view ffprobe_json)
{
    std::vector<AudioTrackDescriptor> tracks;
    if (ffprobe_json.empty() || ffprobe_json.size() > maximum_ffprobe_bytes)
        return tracks;
    json_error_t error{};
    JsonPtr root(json_loadb(ffprobe_json.data(), ffprobe_json.size(), 0, &error));
    if (!root || !json_is_object(root.get()))
        return tracks;
    json_t *streams = json_object_get(root.get(), "streams");
    if (!json_is_array(streams))
        return tracks;
    const std::size_t count = json_array_size(streams);
    for (std::size_t position = 0; position < count; ++position) {
        json_t *stream = json_array_get(streams, position);
        if (!json_is_object(stream))
            continue;
        const std::string codec_type = string_field(stream, "codec_type");
        if (!codec_type.empty() && codec_type != "audio")
            continue;
        if (tracks.size() >= maximum_audio_tracks)
            break;
        AudioTrackDescriptor track;
        track.index = static_cast<int>(tracks.size());
        track.stream_index = numeric_field(stream, "index", -1);
        track.codec = string_field(stream, "codec_name");
        track.channels = numeric_field(stream, "channels", 0);
        track.channel_layout = string_field(stream, "channel_layout");
        track.sample_rate = numeric_field(stream, "sample_rate", 0);
        if (json_t *tags = json_object_get(stream, "tags"); json_is_object(tags)) {
            track.language = string_field(tags, "language");
            track.title = string_field(tags, "title");
        }
        track.browser_compatible = audio_track_browser_compatible(track.codec);
        tracks.push_back(std::move(track));
    }
    return tracks;
}

std::string audio_track_path_name(std::string_view token, int track_index)
{
    if (!lowercase_hex_token(token) || track_index < 0 || track_index >= maximum_audio_tracks)
        return {};
    return "audio-" + std::string(token) + "-t" + std::to_string(track_index);
}

int audio_track_index_from_path(std::string_view path)
{
    constexpr std::string_view prefix = "audio-";
    if (path.size() < prefix.size() + 32 + 3 || !path.starts_with(prefix))
        return -1;
    const std::string_view remainder = path.substr(prefix.size());
    if (remainder.size() < 35 || !lowercase_hex_token(remainder.substr(0, 32)))
        return -1;
    const std::string_view suffix = remainder.substr(32);
    if (suffix.size() < 3 || suffix.size() > 4 || suffix[0] != '-' || suffix[1] != 't')
        return -1;
    const std::string_view digits = suffix.substr(2);
    int index = 0;
    for (const char character : digits) {
        if (character < '0' || character > '9')
            return -1;
        index = index * 10 + (character - '0');
    }
    if (index >= maximum_audio_tracks)
        return -1;
    return index;
}

bool valid_audio_track_path(std::string_view path)
{
    return audio_track_index_from_path(path) >= 0;
}

std::string audio_track_route_arguments(std::string_view source_path, std::string_view audio_path,
                                        int track_index)
{
    if (!route_path_with_prefix(source_path, "direct-") || track_index < 0 ||
        track_index >= maximum_audio_tracks)
        return {};
    if (audio_track_index_from_path(audio_path) != track_index)
        return {};
    return std::string(source_path) + " " + std::string(audio_path) + " audio-track " +
           std::to_string(track_index);
}

} // namespace webobs
