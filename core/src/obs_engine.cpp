#include "webobs/obs_engine.hpp"

#include "webobs/control_server.hpp"
#include "webobs/obs_scene_runtime.hpp"
#include "webobs/redaction.hpp"
#include "webobs/scene_controller.hpp"

#include <obs-nix-platform.h>
#include <obs.h>
#include <callback/calldata.h>
#include <util/base.h>

#include <atomic>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdarg>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace webobs {
namespace {

volatile std::sig_atomic_t stop_requested = 0;

void handle_stop_signal(int)
{
    stop_requested = 1;
}

struct LoggingState {
    explicit LoggingState(int level) : maximum_level(level) {}

    int maximum_level = LOG_INFO;
    std::mutex mutex;
};

struct LogHandlerGuard {
    ~LogHandlerGuard() { base_set_log_handler(nullptr, nullptr); }
};

const char *level_name(int level)
{
    if (level <= LOG_ERROR)
        return "error";
    if (level <= LOG_WARNING)
        return "warn";
    if (level <= LOG_INFO)
        return "info";
    return "debug";
}

void obs_log_handler(int level, const char *format, va_list arguments, void *parameter)
{
    auto *state = static_cast<LoggingState *>(parameter);
    if (!state || level > state->maximum_level)
        return;

    va_list copy;
    va_copy(copy, arguments);
    const int length = std::vsnprintf(nullptr, 0, format, copy);
    va_end(copy);
    if (length < 0)
        return;

    std::vector<char> buffer(static_cast<std::size_t>(length) + 1);
    std::vsnprintf(buffer.data(), buffer.size(), format, arguments);
    std::string message(buffer.data(), static_cast<std::size_t>(length));
    message = redact_rtsp_credentials(message);
    while (!message.empty() && (message.back() == '\n' || message.back() == '\r'))
        message.pop_back();

    std::lock_guard lock(state->mutex);
    std::ostream &stream = level <= LOG_WARNING ? std::cerr : std::cout;
    stream << '[' << level_name(level) << "] " << message << '\n';
    stream.flush();
}

struct ObsCoreGuard {
    bool initialized = false;

    ~ObsCoreGuard()
    {
        if (initialized) {
            while (obs_wait_for_destroy_queue()) {
            }
            obs_shutdown();
        }
    }
};

struct DataDeleter {
    void operator()(obs_data_t *value) const { obs_data_release(value); }
};
struct EncoderDeleter {
    void operator()(obs_encoder_t *value) const { obs_encoder_release(value); }
};
struct OutputDeleter {
    void operator()(obs_output_t *value) const { obs_output_release(value); }
};
struct ServiceDeleter {
    void operator()(obs_service_t *value) const { obs_service_release(value); }
};

using DataPtr = std::unique_ptr<obs_data_t, DataDeleter>;
using EncoderPtr = std::unique_ptr<obs_encoder_t, EncoderDeleter>;
using OutputPtr = std::unique_ptr<obs_output_t, OutputDeleter>;
using ServicePtr = std::unique_ptr<obs_service_t, ServiceDeleter>;

struct TemporaryFileGuard {
    std::filesystem::path path;
    bool keep = false;

    ~TemporaryFileGuard()
    {
        if (!keep && !path.empty()) {
            std::error_code error;
            std::filesystem::remove(path, error);
        }
    }
};

struct OutputState {
    std::atomic_bool stopped = false;
    std::atomic_llong stop_code = 0;
};

void on_output_stopped(void *parameter, calldata_t *data)
{
    auto *state = static_cast<OutputState *>(parameter);
    state->stop_code.store(calldata_int(data, "code"));
    state->stopped.store(true);
}

bool load_module(const std::filesystem::path &prefix, std::string_view module_name)
{
    const std::string name(module_name);
    const std::filesystem::path binary = prefix / "lib" / "obs-plugins" / (name + ".so");
    const std::filesystem::path data = prefix / "share" / "obs" / "obs-plugins" / name;
    obs_module_t *module = nullptr;
    const int result = obs_open_module(&module, binary.c_str(), data.c_str());
    if (result != MODULE_SUCCESS) {
        blog(LOG_ERROR, "Could not open OBS module '%s' (code %d)", name.c_str(), result);
        return false;
    }
    if (!obs_init_module(module)) {
        blog(LOG_ERROR, "Could not initialize OBS module '%s'", name.c_str());
        return false;
    }
    blog(LOG_INFO, "Loaded OBS module '%s'", name.c_str());
    return true;
}

bool prepare_output_paths(const std::filesystem::path &output, const std::filesystem::path &temporary)
{
    std::error_code error;
    if (std::filesystem::exists(output, error)) {
        blog(LOG_ERROR, "Refusing to overwrite existing output file '%s'", output.c_str());
        return false;
    }
    if (std::filesystem::exists(temporary, error)) {
        blog(LOG_ERROR, "Temporary recording file already exists: '%s'", temporary.c_str());
        return false;
    }

    const std::filesystem::path parent = output.parent_path();
    if (parent.empty() || !std::filesystem::is_directory(parent, error)) {
        blog(LOG_ERROR, "Output directory does not exist: '%s'", parent.c_str());
        return false;
    }

    const std::filesystem::path probe = parent / (".webobs-write-test-" + std::to_string(getpid()));
    {
        std::ofstream stream(probe, std::ios::binary | std::ios::trunc);
        if (!stream) {
            blog(LOG_ERROR, "Output directory is not writable: '%s'", parent.c_str());
            return false;
        }
    }
    std::filesystem::remove(probe, error);
    return true;
}

int run_process(const std::vector<std::string> &arguments)
{
    if (arguments.empty())
        return -1;

    const pid_t child = fork();
    if (child < 0)
        return -1;
    if (child == 0) {
        std::vector<char *> raw_arguments;
        raw_arguments.reserve(arguments.size() + 1);
        for (const std::string &argument : arguments)
            raw_arguments.push_back(const_cast<char *>(argument.c_str()));
        raw_arguments.push_back(nullptr);
        execvp(raw_arguments.front(), raw_arguments.data());
        _exit(127);
    }

    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR)
            return -1;
    }
    if (WIFEXITED(status))
        return WEXITSTATUS(status);
    return -1;
}

bool remux_video_only(const std::filesystem::path &temporary, const std::filesystem::path &output)
{
    blog(LOG_INFO, "Finalizing video-only MP4 '%s'", output.c_str());
    const std::vector<std::string> arguments = {
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-i", temporary.string(),
        "-map", "0:v:0", "-an", "-c:v", "copy", "-movflags", "+faststart", output.string(),
    };
    const int status = run_process(arguments);
    if (status != 0) {
        blog(LOG_ERROR, "FFmpeg finalization failed with exit code %d", status);
        std::error_code error;
        std::filesystem::remove(output, error);
        return false;
    }

    std::error_code error;
    if (!std::filesystem::is_regular_file(output, error) || std::filesystem::file_size(output, error) == 0) {
        blog(LOG_ERROR, "Final MP4 is missing or empty");
        std::filesystem::remove(output, error);
        return false;
    }
    return true;
}

bool wait_for_output_stop(obs_output_t *output, OutputState &state, std::string_view label)
{
    obs_output_stop(output);
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(15);
    while ((!state.stopped.load() || obs_output_active(output)) &&
           std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    if (obs_output_active(output)) {
        blog(LOG_WARNING, "%.*s did not stop in time; forcing output shutdown", static_cast<int>(label.size()),
             label.data());
        obs_output_force_stop(output);
        const auto force_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (obs_output_active(output) && std::chrono::steady_clock::now() < force_deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
    }
    if (obs_output_active(output)) {
        blog(LOG_ERROR, "%.*s remained active after forced shutdown", static_cast<int>(label.size()), label.data());
        return false;
    }
    if (!state.stopped.load()) {
        blog(LOG_ERROR, "%.*s stopped without reporting a completion status", static_cast<int>(label.size()),
             label.data());
        return false;
    }
    if (state.stopped.load() && state.stop_code.load() != OBS_OUTPUT_SUCCESS) {
        blog(LOG_ERROR, "%.*s finalization failed (code %lld)", static_cast<int>(label.size()), label.data(),
             state.stop_code.load());
        return false;
    }
    return true;
}

} // namespace

ExitCode run_obs_engine(const Config &config, const SceneDocument &document)
{
    stop_requested = 0;
    std::signal(SIGINT, handle_stop_signal);
    std::signal(SIGTERM, handle_stop_signal);

    LoggingState logging(static_cast<int>(config.log_level));
    base_set_log_handler(obs_log_handler, &logging);
    LogHandlerGuard log_handler_guard;

    std::error_code path_error;
    const std::filesystem::path output_path = std::filesystem::absolute(config.output_path, path_error).lexically_normal();
    if (path_error) {
        blog(LOG_ERROR, "Could not resolve output path: %s", path_error.message().c_str());
        return ExitCode::output_failed;
    }
    const std::filesystem::path temporary_path =
        output_path.parent_path() / ("." + output_path.filename().string() + ".webobsd-" + std::to_string(getpid()) + ".mkv");
    TemporaryFileGuard temporary_guard{temporary_path};
    if (!prepare_output_paths(output_path, temporary_path))
        return ExitCode::output_failed;

    const std::filesystem::path config_directory = "/config/obs";
    std::filesystem::create_directories(config_directory, path_error);
    if (path_error) {
        blog(LOG_ERROR, "Could not create OBS config directory: %s", path_error.message().c_str());
        return ExitCode::obs_initialization_failed;
    }

    obs_set_nix_platform(OBS_NIX_PLATFORM_X11_EGL);
    ObsCoreGuard core;
    if (!obs_startup("en-US", config_directory.c_str(), nullptr)) {
        blog(LOG_ERROR, "obs_startup failed");
        return ExitCode::obs_initialization_failed;
    }
    core.initialized = true;
    obs_video_info video_info{};
    video_info.graphics_module = "libobs-opengl";
    video_info.fps_num = static_cast<uint32_t>(config.fps);
    video_info.fps_den = 1;
    video_info.base_width = static_cast<uint32_t>(document.canvas.width);
    video_info.base_height = static_cast<uint32_t>(document.canvas.height);
    video_info.output_width = static_cast<uint32_t>(document.canvas.width);
    video_info.output_height = static_cast<uint32_t>(document.canvas.height);
    video_info.output_format = VIDEO_FORMAT_NV12;
    video_info.adapter = 0;
    video_info.gpu_conversion = true;
    video_info.colorspace = VIDEO_CS_709;
    video_info.range = VIDEO_RANGE_PARTIAL;
    video_info.scale_type = OBS_SCALE_BICUBIC;
    const int video_result = obs_reset_video(&video_info);
    if (video_result != OBS_VIDEO_SUCCESS) {
        blog(LOG_ERROR, "obs_reset_video failed (code %d)", video_result);
        return ExitCode::obs_initialization_failed;
    }

    obs_audio_info audio_info{};
    audio_info.samples_per_sec = 48000;
    audio_info.speakers = SPEAKERS_STEREO;
    if (!obs_reset_audio(&audio_info)) {
        blog(LOG_ERROR, "obs_reset_audio failed");
        return ExitCode::obs_initialization_failed;
    }

    const std::filesystem::path obs_prefix = WEBOBS_OBS_PREFIX;
    if (!load_module(obs_prefix, "obs-ffmpeg") || !load_module(obs_prefix, "obs-x264") ||
        (config.webrtc_enabled && !load_module(obs_prefix, "obs-webrtc")))
        return ExitCode::obs_initialization_failed;
    obs_post_load_modules();

    ObsSceneRuntime scene_runtime(config.connect_timeout_seconds);
    if (const auto prepare_error = scene_runtime.prepare(document)) {
        blog(LOG_ERROR, "Could not prepare OBS scene: %s", prepare_error->c_str());
        return ExitCode::obs_initialization_failed;
    }
    scene_runtime.commit_prepared();
    scene_runtime.activate();
    const std::size_t expected_sources = scene_runtime.visible_source_count();
    if (expected_sources == 0) {
        blog(LOG_INFO, "Scene has no visible RTSP sources; recording starts with a black canvas");
    } else {
        blog(LOG_INFO, "Waiting up to %d seconds for %zu visible RTSP source(s)", config.connect_timeout_seconds,
             expected_sources);
        const auto source_deadline =
            std::chrono::steady_clock::now() + std::chrono::seconds(config.connect_timeout_seconds);
        while (!stop_requested && std::chrono::steady_clock::now() < source_deadline) {
            if (scene_runtime.ready_visible_source_count() == expected_sources)
                break;
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        if (stop_requested) {
            blog(LOG_INFO, "Stopped before recording began");
            return ExitCode::success;
        }
        const std::size_t ready_sources = scene_runtime.ready_visible_source_count();
        if (ready_sources == 0 && config.scene_file.empty()) {
            blog(LOG_ERROR, "No visible RTSP source produced a video frame before the timeout");
            return ExitCode::source_timeout;
        }
        if (ready_sources < expected_sources) {
            const std::vector<std::string> pending = scene_runtime.pending_visible_source_ids();
            std::string identifiers;
            for (const std::string &id : pending) {
                if (!identifiers.empty())
                    identifiers += ',';
                identifiers += id;
            }
            blog(LOG_WARNING, "%zu of %zu visible RTSP sources are ready; pending source ids: %s", ready_sources,
                 expected_sources, identifiers.c_str());
        } else {
            blog(LOG_INFO, "All %zu visible RTSP source(s) are ready", ready_sources);
        }
    }

    DataPtr video_settings(obs_data_create());
    obs_data_set_string(video_settings.get(), "rate_control", "CBR");
    obs_data_set_int(video_settings.get(), "bitrate", config.bitrate_kbps);
    obs_data_set_int(video_settings.get(), "keyint_sec", 2);
    obs_data_set_string(video_settings.get(), "preset", "veryfast");
    obs_data_set_string(video_settings.get(), "profile", "high");
    ServicePtr whip_service;
    if (config.webrtc_enabled) {
        DataPtr service_settings(obs_data_create());
        obs_data_set_string(service_settings.get(), "server", config.whip_url.c_str());
        obs_data_set_string(service_settings.get(), "bearer_token", "");
        whip_service.reset(obs_service_create("whip_custom", "WebOBS WHIP service", service_settings.get(), nullptr));
        if (!whip_service) {
            blog(LOG_ERROR, "Could not create the WHIP service");
            return ExitCode::output_failed;
        }
        obs_service_apply_encoder_settings(whip_service.get(), video_settings.get(), nullptr);
    }
    EncoderPtr video_encoder(obs_video_encoder_create("obs_x264", "WebOBS x264", video_settings.get(), nullptr));
    if (!video_encoder) {
        blog(LOG_ERROR, "Could not create obs_x264 encoder");
        return ExitCode::output_failed;
    }
    obs_encoder_set_video(video_encoder.get(), obs_get_video());

    DataPtr audio_settings(obs_data_create());
    obs_data_set_int(audio_settings.get(), "bitrate", 64);
    EncoderPtr audio_encoder(
        obs_audio_encoder_create("ffmpeg_aac", "WebOBS silent AAC", audio_settings.get(), 0, nullptr));
    if (!audio_encoder) {
        blog(LOG_ERROR, "Could not create temporary AAC encoder required by ffmpeg_muxer");
        return ExitCode::output_failed;
    }
    obs_encoder_set_audio(audio_encoder.get(), obs_get_audio());

    DataPtr output_settings(obs_data_create());
    obs_data_set_string(output_settings.get(), "path", temporary_path.c_str());
    obs_data_set_bool(output_settings.get(), "allow_overwrite", true);
    OutputState output_state;
    OutputPtr output(obs_output_create("ffmpeg_muxer", "WebOBS file output", output_settings.get(), nullptr));
    if (!output) {
        blog(LOG_ERROR, "Could not create ffmpeg_muxer output");
        return ExitCode::output_failed;
    }
    signal_handler_connect(obs_output_get_signal_handler(output.get()), "stop", on_output_stopped, &output_state);
    obs_output_set_video_encoder(output.get(), video_encoder.get());
    obs_output_set_audio_encoder(output.get(), audio_encoder.get(), 0);

    OutputState whip_output_state;
    OutputPtr whip_output;
    if (config.webrtc_enabled) {
        whip_output.reset(obs_output_create("whip_output_video", "WebOBS WHIP video output", nullptr, nullptr));
        if (!whip_output) {
            blog(LOG_ERROR, "Could not create the WHIP video output");
            return ExitCode::output_failed;
        }
        signal_handler_connect(obs_output_get_signal_handler(whip_output.get()), "stop", on_output_stopped,
                               &whip_output_state);
        obs_output_set_video_encoder(whip_output.get(), video_encoder.get());
        obs_output_set_service(whip_output.get(), whip_service.get());
    }

    SceneController scene_controller(document, config.scene_file, scene_runtime);
    ControlServer control_server(config, scene_controller);
    if (const auto server_error = control_server.start()) {
        blog(LOG_ERROR, "Could not start the HTTP control server: %s", server_error->c_str());
        return ExitCode::control_server_failed;
    }
    if (config.http_port != 0) {
        blog(LOG_INFO, "HTTP control server listening on %s:%d", config.listen_address.c_str(), config.http_port);
        if (config.allow_insecure_remote)
            blog(LOG_WARNING, "HTTP control listener has no M6 authentication; keep the published host port local");
    }

    if (whip_output && !obs_output_start(whip_output.get())) {
        const char *message = obs_output_get_last_error(whip_output.get());
        blog(LOG_ERROR, "Could not start WebRTC publishing%s%s", message && *message ? ": " : "",
             message && *message ? message : "");
        control_server.stop();
        return ExitCode::output_failed;
    }
    if (whip_output)
        blog(LOG_INFO, "WebRTC program publishing started");

    if (!obs_output_start(output.get())) {
        const char *message = obs_output_get_last_error(output.get());
        blog(LOG_ERROR, "Could not start recording%s%s", message && *message ? ": " : "",
             message && *message ? message : "");
        control_server.stop();
        if (whip_output && obs_output_active(whip_output.get()))
            wait_for_output_stop(whip_output.get(), whip_output_state, "WebRTC output");
        return ExitCode::output_failed;
    }
    blog(LOG_INFO, "Recording started: %dx%d at %d fps, %d Kbps", document.canvas.width,
         document.canvas.height, config.fps, config.bitrate_kbps);

    const auto recording_started = std::chrono::steady_clock::now();
    bool unexpected_stop = false;
    while (!stop_requested) {
        if (config.duration_seconds > 0 &&
            std::chrono::steady_clock::now() - recording_started >= std::chrono::seconds(config.duration_seconds))
            break;
        if (output_state.stopped.load()) {
            unexpected_stop = true;
            break;
        }
        if (whip_output && whip_output_state.stopped.load()) {
            unexpected_stop = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    if (unexpected_stop) {
        control_server.stop();
        if (whip_output_state.stopped.load())
            blog(LOG_ERROR, "WebRTC publishing stopped unexpectedly (code %lld)", whip_output_state.stop_code.load());
        if (output_state.stopped.load())
            blog(LOG_ERROR, "Recording stopped unexpectedly (code %lld)", output_state.stop_code.load());
        if (whip_output && obs_output_active(whip_output.get()))
            wait_for_output_stop(whip_output.get(), whip_output_state, "WebRTC output");
        if (obs_output_active(output.get()))
            wait_for_output_stop(output.get(), output_state, "Recording output");
        whip_output.reset();
        output.reset();
        return ExitCode::output_failed;
    }
    control_server.stop();
    bool outputs_stopped = true;
    if (whip_output)
        outputs_stopped = wait_for_output_stop(whip_output.get(), whip_output_state, "WebRTC output");
    whip_output.reset();
    whip_service.reset();
    if (!wait_for_output_stop(output.get(), output_state, "Recording output"))
        outputs_stopped = false;
    if (!outputs_stopped) {
        output.reset();
        return ExitCode::output_failed;
    }
    output.reset();
    video_encoder.reset();
    audio_encoder.reset();
    scene_runtime.deactivate();

    if (!std::filesystem::is_regular_file(temporary_path, path_error) ||
        std::filesystem::file_size(temporary_path, path_error) == 0) {
        blog(LOG_ERROR, "Temporary recording is missing or empty");
        return ExitCode::output_failed;
    }
    if (!remux_video_only(temporary_path, output_path))
        return ExitCode::remux_failed;

    std::filesystem::remove(temporary_path, path_error);
    if (path_error)
        blog(LOG_WARNING, "Could not remove temporary recording '%s': %s", temporary_path.c_str(),
             path_error.message().c_str());
    blog(LOG_INFO, "Recording complete: '%s'", output_path.c_str());
    return ExitCode::success;
}

} // namespace webobs
