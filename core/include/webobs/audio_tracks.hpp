#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace webobs {

/**
 * One real audio track of a source as reported by ffprobe.
 *
 * c index is the position inside the audio streams (c 0:a:<index>) and is what
 * the per-track audio-only route extracts; c stream_index keeps ffprobe's
 * absolute stream index so callers can display both without renumbering.
 */
struct AudioTrackDescriptor {
    int index = 0;
    int stream_index = -1;
    std::string codec;
    int channels = 0;
    std::string channel_layout;
    int sample_rate = 0;
    std::string language;
    std::string title;
    bool browser_compatible = false;
};

/** Parse c ffprobe -of json -select_streams a output.  Malformed input yields no tracks. */
[[nodiscard]] std::vector<AudioTrackDescriptor> parse_audio_tracks(std::string_view ffprobe_json);

/** WebRTC-capable audio codecs the browser can play without server transcoding. */
[[nodiscard]] bool audio_track_browser_compatible(std::string_view codec);

/**
 * MediaMTX path name for an audio-only per-track route.  Returns an empty string
 * when the token or the track index is unusable, so a caller can never publish
 * to an unexpected path.
 */
[[nodiscard]] std::string audio_track_path_name(std::string_view token, int track_index);

/** True only for paths this build generates (c audio-<32 hex>-t<index>). */
[[nodiscard]] bool valid_audio_track_path(std::string_view path);

/** Track index encoded in an audio-only path, or -1 when the path is invalid. */
[[nodiscard]] int audio_track_index_from_path(std::string_view path);

/**
 * Arguments for the on-demand transcoder that extract one audio track as an
 * audio-only Opus stream.  Empty when any input is unusable.
 */
[[nodiscard]] std::string audio_track_route_arguments(std::string_view source_path,
                                                      std::string_view audio_path,
                                                      int track_index);

} // namespace webobs
