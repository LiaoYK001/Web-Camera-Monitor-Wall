#pragma once
#include "webobs/receiver_codecs.hpp"
#include <string>
template<class Expect> void receiver_codec_tests(Expect expect)
{
    const std::string native="v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96 102\r\na=recvonly\r\na=rtpmap:96 H264/90000\r\na=rtpmap:102 H265/90000\r\n";
    expect(webobs::receiver_offers_hevc(native),"active offered H265 video is recognized");
    expect(!webobs::receiver_offers_hevc("m=audio 9 UDP/TLS/RTP/SAVPF 102\r\na=rtpmap:102 H265/90000\r\n"),"audio section cannot enable native video");
    expect(!webobs::receiver_offers_hevc("m=video 0 UDP/TLS/RTP/SAVPF 102\r\na=rtpmap:102 H265/90000\r\n"),"disabled video cannot enable native decode");
    expect(!webobs::receiver_offers_hevc("m=video 9 UDP/TLS/RTP/SAVPF 96\r\na=rtpmap:102 H265/90000\r\n"),"unoffered payload cannot enable native decode");
    expect(!webobs::receiver_offers_hevc(native+"a=inactive\r\n"),"inactive receiver cannot enable native decode");
    expect(!webobs::receiver_offers_hevc("a=inactive\r\nm=video 9 UDP/TLS/RTP/SAVPF 102\r\na=rtpmap:102 H265/90000\r\n"),"session direction applies to video");
    expect(webobs::receiver_offers_hevc("a=inactive\r\n"+native),"media direction overrides session direction");
    expect(webobs::hevc_passthrough_allowed("hevc",true,false,true,false),"qualified HEVC can bypass video conversion");
    expect(!webobs::hevc_passthrough_allowed("hevc",false,false,true,false),"unknown reordering never counts as zero B frames");
    expect(!webobs::hevc_passthrough_allowed("hevc",true,true,true,false),"reordered HEVC keeps compatibility conversion");
    expect(!webobs::hevc_passthrough_allowed("hevc",true,false,false,false),"older receiver keeps H264 conversion");
    expect(!webobs::hevc_passthrough_allowed("hevc",true,false,true,true),"explicit Hybrid video policy is honored");
}
