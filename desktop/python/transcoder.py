"""Windows MediaMTX on-demand paths, equivalent to the POSIX helper."""
import os
import pathlib
import re
import subprocess
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from runtime_support import service_rtsp

def arguments(values, encoder="libx264"):
    if len(values) != 4:
        raise ValueError("invalid argument count")
    source, target, video, audio = values
    direct = bool(re.fullmatch(r"direct-[a-f0-9]{32}", source))
    url = bool(re.fullmatch(r"rtsps?://[!-~]{1,2048}", source))
    if not direct and not url:
        raise ValueError("invalid source")
    ffmpeg = os.environ["WEBOBS_FFMPEG_PATH"]
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-rtsp_transport", "tcp", "-timeout", "8000000",
            "-i", service_rtsp(8554, "/" + source) if direct else source]
    if video == "audio-track":
        if not re.fullmatch(r"([0-9]|[12][0-9]|3[01])", audio) or target != f"audio-{target[6:38]}-t{audio}" or not re.fullmatch(r"audio-[a-f0-9]{32}-t\d{1,2}", target):
            raise ValueError("invalid track")
        args += ["-map", f"0:a:{audio}", "-vn"]
    elif video == "audio-mix":
        if not re.fullmatch(r"mix-[a-f0-9]{32}", target): raise ValueError("invalid mix destination")
        tracks = audio.split(",")
        if not 1 <= len(tracks) <= 8: raise ValueError("invalid mix count")
        parsed = []
        for track in tracks:
            match = re.fullmatch(r"([0-9]|[12][0-9]|3[01]):(0(?:\.\d{1,4})?|1(?:\.0{1,4})?):([01])(?::(-?(?:0|[1-9][0-9]{0,4})))?", track)
            if not match: raise ValueError("invalid mix track")
            index, gain, muted, delay = match.groups(); delay = int(delay or 0)
            if abs(delay) > 10000: raise ValueError("invalid delay")
            parsed.append((index, "0" if muted == "1" else gain, delay))
        normalization = max(0, -min(item[2] for item in parsed))
        graph = "".join(f"[0:a:{index}]adelay=delays={normalization+delay}:all=1,volume={gain}[m{i}];" for i,(index,gain,delay) in enumerate(parsed))
        graph += "".join(f"[m{i}]" for i in range(len(parsed))) + f"amix=inputs={len(parsed)}:normalize=0[amixed]"
        args += ["-filter_complex", graph, "-map", "0:v", "-map", "[amixed]", "-c:v", "copy"]
        if normalization: args += ["-bsf:v", f"setts=ts=TS+{normalization}/(1000*TB)"]
    elif video in {"copy", "transcode"}:
        if not direct or not re.fullmatch(r"hybrid-[a-f0-9]{32}", target) or audio not in {"copy", "transcode"}: raise ValueError("invalid hybrid path")
        args += ["-map", "0:v:0", "-map", "0:a:0?"]
        if video == "copy": args += ["-c:v", "copy"]
        elif encoder == "h264_nvenc":
            bitrate = str(max(100, min(50000, int(os.environ.get("WEBOBS_HYBRID_BITRATE_KBPS", "4000"))))) + "k"
            args += ["-c:v", encoder, "-preset", "p1", "-tune", "ll", "-rc", "cbr", "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bitrate, "-bf", "0", "-g", "60", "-pix_fmt", "yuv420p"]
        else: args += ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-profile:v", "high", "-x264-params", "sliced-threads=0", "-pix_fmt", "yuv420p", "-bf", "0", "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*2)"]
    else: raise ValueError("invalid mode")
    if video in {"copy", "transcode"} and audio == "copy": args += ["-c:a", "copy"]
    else: args += ["-c:a", "libopus", "-b:a", "96k", "-ar", "48000", "-ac", "2"]
    return args + ["-rtsp_transport", "tcp", "-f", "rtsp", service_rtsp(8554, "/"+target)]

if __name__ == "__main__":
    try:
        values = sys.argv[1:]
        if len(values) == 4 and values[2] == "transcode" and os.environ.get("WEBOBS_NVIDIA_ENCODE_SUPPORTED") == "true" and os.environ.get("WEBOBS_HYBRID_VIDEO_ENCODER") != "x264":
            result = subprocess.call(arguments(values, "h264_nvenc"))
            if result == 0: raise SystemExit(0)
            if os.environ.get("WEBOBS_SOFTWARE_FALLBACK", "true") != "true": raise SystemExit(result)
        raise SystemExit(subprocess.call(arguments(values)))
    except (ValueError, KeyError):
        print("invalid internal transcoder configuration", file=sys.stderr)
        raise SystemExit(2)
