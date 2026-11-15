#pragma once
#include <charconv>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_set>

namespace webobs {
// Read the actual active video offer, not an MSE capability or a codec name in
// an unrelated SDP section. Upstream still performs full SDP validation.
inline bool receiver_offers_hevc(std::string_view sdp)
{
    if (sdp.size() > 64 * 1024) return false;
    bool video = false, active = false, receiving = true, hevc = false;
    bool media_seen = false, session_receiving = true;
    std::unordered_set<unsigned> payloads;
    const auto payload = [](std::string_view value, unsigned& result) {
        const auto parsed = std::from_chars(value.data(), value.data()+value.size(), result);
        return parsed.ec == std::errc{} && parsed.ptr == value.data()+value.size() && result <= 127;
    };
    std::istringstream lines{std::string(sdp)};
    std::string line;
    while (std::getline(lines, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.starts_with("m=")) {
            if (video && active && receiving && hevc) return true;
            std::istringstream media(line.substr(2));
            std::string kind, port, protocol, token;
            media >> kind >> port >> protocol;
            video = kind == "video"; active = port != "0" && protocol.find("RTP/") != std::string::npos;
            media_seen = true;
            receiving = session_receiving; hevc = false; payloads.clear();
            while (media >> token) { unsigned id; if (payload(token,id)) payloads.insert(id); }
        } else if (line == "a=inactive" || line == "a=sendonly" || line == "a=recvonly" || line == "a=sendrecv") {
            const bool receives = line == "a=recvonly" || line == "a=sendrecv";
            if (!media_seen) session_receiving = receives;
            else if (video) receiving = receives;
        } else if (video && line.starts_with("a=rtpmap:")) {
            const auto space = line.find(' ',9);
            if (space == std::string::npos) continue;
            unsigned id;
            if (!payload(std::string_view(line).substr(9,space-9),id) || !payloads.contains(id)) continue;
            std::string codec = line.substr(space+1);
            for (char& character : codec) if (character >= 'A' && character <= 'Z') character += 'a'-'A';
            if (codec == "h265/90000") hevc = true;
        }
    }
    return video && active && receiving && hevc;
}

inline bool hevc_passthrough_allowed(std::string_view codec, bool known, bool reordering,
                                     bool receiver, bool force_transcode)
{
    return (codec == "hevc" || codec == "h265") && known && !reordering && receiver && !force_transcode;
}
}
