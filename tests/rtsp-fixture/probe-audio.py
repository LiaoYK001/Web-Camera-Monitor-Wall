#!/usr/bin/env python3
import argparse
import array
import json
import math
import statistics
import subprocess


def run(*arguments: str) -> bytes:
    return subprocess.check_output(arguments, stderr=subprocess.DEVNULL)


def metadata(path: str) -> dict:
    value = json.loads(run(
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path
    ))
    video = next(stream for stream in value["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in value["streams"] if stream["codec_type"] == "audio")
    if video["codec_name"] != "h264":
        raise RuntimeError(f"{path}: expected H.264 video")
    if audio["codec_name"] != "aac" or audio.get("sample_rate") != "48000" or audio.get("channels") != 2:
        raise RuntimeError(f"{path}: expected 48 kHz stereo AAC")
    duration = float(value["format"]["duration"])
    if duration < 8:
        raise RuntimeError(f"{path}: recording is too short")
    subprocess.check_call(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
        stdout=subprocess.DEVNULL,
    )
    return {"duration": duration, "fps": fraction(video["avg_frame_rate"])}


def fraction(value: str) -> float:
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator)


def floats(payload: bytes) -> array.array:
    values = array.array("f")
    values.frombytes(payload)
    return values


def band_rms(path: str, frequency: int) -> float:
    samples = floats(run(
        "ffmpeg", "-v", "error", "-ss", "2", "-t", "6", "-i", path, "-map", "0:a:0",
        "-ac", "1", "-ar", "48000", "-af", f"bandpass=f={frequency}:w=70", "-f", "f32le", "-",
    ))
    if not samples:
        raise RuntimeError(f"{path}: no decoded audio samples")
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def audio_onsets(path: str) -> list[float]:
    samples = floats(run(
        "ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-ac", "1", "-ar", "48000",
        "-f", "f32le", "-",
    ))
    window = 480
    levels = [
        math.sqrt(sum(value * value for value in samples[index:index + window]) / window)
        for index in range(0, len(samples) - window + 1, window)
    ]
    threshold = max(levels) * 0.30
    onsets: list[float] = []
    active = False
    for index, level in enumerate(levels):
        next_active = level >= threshold
        if next_active and not active:
            timestamp = index * 0.01
            if not onsets or timestamp - onsets[-1] > 0.5:
                onsets.append(timestamp)
        active = next_active
    return onsets


def video_onsets(path: str, fps: float) -> list[float]:
    frames = run(
        "ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-vf", "scale=1:1:flags=area,format=gray",
        "-f", "rawvideo", "-",
    )
    onsets: list[float] = []
    active = False
    for index, level in enumerate(frames):
        next_active = level >= 150
        if next_active and not active:
            timestamp = index / fps
            if not onsets or timestamp - onsets[-1] > 0.5:
                onsets.append(timestamp)
        active = next_active
    return onsets


def circular(value: float) -> float:
    while value > 0.5:
        value -= 1.0
    while value < -0.5:
        value += 1.0
    return value


def sync_deltas(path: str, fps: float) -> list[float]:
    audio = audio_onsets(path)
    video = video_onsets(path, fps)
    if len(audio) < 6 or len(video) < 6:
        raise RuntimeError(f"{path}: insufficient AV synchronization pulses")
    usable_video = [timestamp for timestamp in video if timestamp > 1 and timestamp < video[-1] - 1]
    return [circular(min(audio, key=lambda candidate: abs(candidate - timestamp)) - timestamp)
            for timestamp in usable_video]


def assert_between(value: float, minimum: float, maximum: float, label: str) -> None:
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{label}: {value:.4f} is outside [{minimum:.4f}, {maximum:.4f}]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", required=True)
    parser.add_argument("--quarter", required=True)
    parser.add_argument("--muted", required=True)
    parser.add_argument("--sync-zero", required=True)
    parser.add_argument("--sync-offset", required=True)
    args = parser.parse_args()

    details = {path: metadata(path) for path in vars(args).values()}
    full_440 = band_rms(args.full, 440)
    full_880 = band_rms(args.full, 880)
    quarter_440 = band_rms(args.quarter, 440)
    quarter_880 = band_rms(args.quarter, 880)
    muted_440 = band_rms(args.muted, 440)
    muted_880 = band_rms(args.muted, 880)
    if min(full_440, full_880, quarter_440, quarter_880, muted_440) <= 0.001:
        raise RuntimeError("expected audible frequency bands were not present")
    assert_between(quarter_880 / full_880, 0.15, 0.40, "quarter-volume 880 Hz ratio")
    assert_between(muted_880 / full_880, 0.0, 0.10, "muted 880 Hz ratio")
    assert_between(quarter_440 / full_440, 0.75, 1.30, "unmodified 440 Hz ratio")
    assert_between(muted_440 / full_440, 0.75, 1.30, "440 Hz ratio after muting peer")

    zero_deltas = sync_deltas(args.sync_zero, details[args.sync_zero]["fps"])
    offset_deltas = sync_deltas(args.sync_offset, details[args.sync_offset]["fps"])
    zero_median = statistics.median(zero_deltas)
    offset_median = statistics.median(offset_deltas)
    offset_effect = circular(offset_median - zero_median)
    assert_between(offset_effect, 0.19, 0.31, "250 ms libobs sync-offset effect")
    zero_drift = abs(circular(statistics.median(zero_deltas[-4:]) - statistics.median(zero_deltas[:4])))
    offset_drift = abs(circular(statistics.median(offset_deltas[-4:]) - statistics.median(offset_deltas[:4])))
    assert_between(zero_drift, 0.0, 0.06, "baseline AV drift")
    assert_between(offset_drift, 0.0, 0.06, "offset AV drift")

    print(
        "M5 audio recording verification passed: "
        f"quarter_ratio={quarter_880 / full_880:.3f} muted_ratio={muted_880 / full_880:.3f} "
        f"sync_effect_ms={offset_effect * 1000:.1f} zero_drift_ms={zero_drift * 1000:.1f} "
        f"offset_drift_ms={offset_drift * 1000:.1f}"
    )


if __name__ == "__main__":
    main()
