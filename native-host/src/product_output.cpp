#include "product_output.hpp"

#include <obs.h>

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QHostAddress>
#include <QProcess>
#include <QSaveFile>
#include <QTcpServer>
#include <QTcpSocket>
#include <QThread>
#include <QUdpSocket>

#include <algorithm>
#include <memory>
#include <utility>

namespace webobs::native_host {
namespace {
struct Data {
	obs_data_t *value = nullptr;
	explicit Data(obs_data_t *data = nullptr) : value(data) {}
	~Data() { if (value) obs_data_release(value); }
	Data(const Data &) = delete;
	Data &operator=(const Data &) = delete;
	obs_data_t *get() const { return value; }
};
struct Encoder {
	obs_encoder_t *value = nullptr;
	~Encoder() { if (value) obs_encoder_release(value); }
	Encoder() = default;
	Encoder(const Encoder &) = delete;
	Encoder &operator=(const Encoder &) = delete;
	void reset(obs_encoder_t *next = nullptr)
	{
		if (value) obs_encoder_release(value);
		value = next;
	}
};
struct Output {
	obs_output_t *value = nullptr;
	~Output() { if (value) obs_output_release(value); }
	Output() = default;
	Output(const Output &) = delete;
	Output &operator=(const Output &) = delete;
	void reset(obs_output_t *next = nullptr)
	{
		if (value) obs_output_release(value);
		value = next;
	}
};
struct Service {
	obs_service_t *value = nullptr;
	~Service() { if (value) obs_service_release(value); }
	Service() = default;
	Service(const Service &) = delete;
	Service &operator=(const Service &) = delete;
	void reset(obs_service_t *next = nullptr)
	{
		if (value) obs_service_release(value);
		value = next;
	}
};

QString runtime_root()
{
	return QDir(QCoreApplication::applicationDirPath()).absoluteFilePath("../..");
}

QString bounded_error(const char *value)
{
	if (!value) return {};
	const QString text = QString::fromUtf8(value).simplified();
	return text.left(200);
}

int free_tcp_port()
{
	QTcpServer server;
	if (!server.listen(QHostAddress::LocalHost, 0)) return 0;
	const int port = int(server.serverPort());
	server.close();
	return port;
}

int free_udp_port()
{
	QUdpSocket socket;
	if (!socket.bind(QHostAddress::LocalHost, 0)) return 0;
	const int port = int(socket.localPort());
	socket.close();
	return port;
}

bool port_available(int port)
{
	QTcpServer server;
	if (!server.listen(QHostAddress::LocalHost, quint16(port))) return false;
	server.close();
	return true;
}

void wait_ms(int milliseconds)
{
	QThread::msleep(static_cast<unsigned long>(milliseconds));
}

bool wait_output_inactive(obs_output_t *output, int timeout_ms)
{
	QElapsedTimer timer;
	timer.start();
	while (obs_output_active(output) && timer.elapsed() < timeout_ms) wait_ms(50);
	return !obs_output_active(output);
}

QString media_mtx_config(int api_port, int rtsp_port, int udp_port)
{
	return QStringLiteral(
		"logLevel: warn\n"
		"logDestinations: [stderr]\n"
		"authMethod: internal\n"
		"authInternalUsers:\n"
		"  - user: any\n"
		"    pass:\n"
		"    ips: [127.0.0.1, ::1]\n"
		"    permissions:\n"
		"      - action: publish\n"
		"        path: program\n"
		"      - action: read\n"
		"        path: program\n"
		"      - action: api\n"
		"api: true\n"
		"apiAddress: 127.0.0.1:%1\n"
		"apiEncryption: false\n"
		"metrics: false\n"
		"pprof: false\n"
		"playback: false\n"
		"rtsp: true\n"
		"rtspTransports: [tcp]\n"
		"rtspEncryption: \"no\"\n"
		"rtspAddress: 127.0.0.1:%2\n"
		"rtmp: false\n"
		"hls: false\n"
		"srt: false\n"
		"webrtc: true\n"
		"webrtcAddress: 127.0.0.1:8889\n"
		"webrtcEncryption: false\n"
		"webrtcAllowOrigins: ['*']\n"
		"webrtcTrustedProxies: []\n"
		"webrtcLocalUDPAddress: 127.0.0.1:%3\n"
		"webrtcLocalTCPAddress: ''\n"
		"webrtcIPsFromInterfaces: false\n"
		"webrtcAdditionalHosts: [127.0.0.1]\n"
		"webrtcICEServers2: []\n"
		"webrtcTrackGatherTimeout: 12s\n"
		"pathDefaults:\n"
		"  source: publisher\n"
		"  overridePublisher: false\n"
		"paths:\n"
		"  program:\n").arg(api_port).arg(rtsp_port).arg(udp_port);
}

} // namespace

struct ProductProgramOutputImpl {
	QString data_root;
	QString recordings_root;
	QString final_path;
	QString temporary_path;
	QString recording_error;
	QString stream_error;
	QString stream_publish_url;
	QString stream_playback_url;
	bool recording = false;
	bool recording_ready = false;
	bool streaming = false;
	qint64 recording_bytes = 0;
	qint64 completed_seconds = 0;
	QElapsedTimer recording_clock;
	QElapsedTimer stream_clock;
	QProcess media_mtx;
	Output recording_output;
	Encoder recording_video;
	Encoder recording_audio;
	Output whip_output;
	Encoder whip_video;
	Encoder whip_audio;
	Service whip_service;

	explicit ProductProgramOutputImpl(QString root) : data_root(std::move(root))
	{
		recordings_root = qEnvironmentVariable("WEBOBS_PROGRAM_RECORDINGS");
		if (recordings_root.isEmpty())
			recordings_root = QDir(data_root).absoluteFilePath("../recordings");
	}
	~ProductProgramOutputImpl() { shutdown(); }

	void release_recording()
	{
		recording_output.reset();
		recording_video.reset();
		recording_audio.reset();
	}
	void release_streaming()
	{
		whip_output.reset();
		whip_video.reset();
		whip_audio.reset();
		whip_service.reset();
	}
	void stop_media_mtx()
	{
		if (media_mtx.state() == QProcess::NotRunning) return;
		media_mtx.terminate();
		if (!media_mtx.waitForFinished(5000)) {
			media_mtx.kill();
			media_mtx.waitForFinished(3000);
		}
	}
	bool start_media_mtx(QString &error)
	{
		stop_media_mtx();
		stream_error.clear();
		const QString binary = QDir(runtime_root()).absoluteFilePath("bin/mediamtx.exe");
		if (!QFileInfo(binary).isFile()) {
			error = "mediamtx-unavailable";
			return false;
		}
		if (!port_available(8889)) {
			error = "whip-port-unavailable";
			return false;
		}
		const int api_port = free_tcp_port();
		const int rtsp_port = free_tcp_port();
		const int udp_port = free_udp_port();
		if (!api_port || !rtsp_port || !udp_port) {
			error = "mediamtx-port-failed";
			return false;
		}
		QDir run_dir(QDir(data_root).absoluteFilePath("run/program-output"));
		if (!run_dir.exists() && !QDir().mkpath(run_dir.absolutePath())) {
			error = "mediamtx-directory-failed";
			return false;
		}
		const QString config_path = run_dir.absoluteFilePath("mediamtx.yml");
		QSaveFile config(config_path);
		if (!config.open(QIODevice::WriteOnly) ||
		    config.write(media_mtx_config(api_port, rtsp_port, udp_port).toUtf8()) < 0 ||
		    !config.commit()) {
			error = "mediamtx-config-failed";
			return false;
		}
		media_mtx.setProcessChannelMode(QProcess::MergedChannels);
		media_mtx.start(binary, {config_path});
		if (!media_mtx.waitForStarted(5000)) {
			error = "mediamtx-start-failed";
			return false;
		}
		QElapsedTimer readiness;
		readiness.start();
		while (readiness.elapsed() < 10000) {
			if (media_mtx.state() == QProcess::NotRunning) {
				const QString tail = QString::fromUtf8(media_mtx.readAll()).simplified().left(160);
				stream_error = tail.isEmpty() ? "mediamtx-exited" : "mediamtx-exited: " + tail;
				error = "mediamtx-exited";
				return false;
			}
			QTcpSocket probe;
			probe.connectToHost(QHostAddress::LocalHost, quint16(api_port));
			if (probe.waitForConnected(200)) {
				probe.disconnectFromHost();
				stream_publish_url =
					QStringLiteral("http://127.0.0.1:8889/program/whip");
				stream_playback_url =
					QStringLiteral("rtsp://127.0.0.1:%1/program").arg(rtsp_port);
				return true;
			}
			wait_ms(100);
		}
		stop_media_mtx();
		error = "mediamtx-timeout";
		return false;
	}
	bool start_recording(QString &error)
	{
		if (recording) return error = "recording-active", false;
		recording_error.clear();
		recording_ready = false;
		if (!QDir().mkpath(recordings_root)) {
			error = "recording-directory-failed";
			return false;
		}
		const QString stamp = QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss");
		final_path = QDir(recordings_root).absoluteFilePath("Program " + stamp + ".mp4");
		temporary_path = QDir(recordings_root).absoluteFilePath(
			".Program " + stamp + ".webobs-recording-" +
			QString::number(QCoreApplication::applicationPid()) + ".mkv");
		Data video_settings(obs_data_create());
		obs_data_set_string(video_settings.get(), "rate_control", "CBR");
		obs_data_set_int(video_settings.get(), "bitrate", 6000);
		obs_data_set_int(video_settings.get(), "keyint_sec", 2);
		obs_data_set_string(video_settings.get(), "preset", "veryfast");
		obs_data_set_string(video_settings.get(), "profile", "high");
		obs_encoder_t *video = obs_video_encoder_create("obs_x264", "WebOBS Program recording x264",
			video_settings.get(), nullptr);
		if (!video) {
			error = "recording-encoder-unavailable";
			return false;
		}
		recording_video.reset(video);
		obs_encoder_set_video(recording_video.value, obs_get_video());
		obs_data_t *audio_settings = obs_data_create();
		obs_data_set_int(audio_settings, "bitrate", 128);
		obs_encoder_t *audio = obs_audio_encoder_create("ffmpeg_aac", "WebOBS Program recording AAC",
			audio_settings, 0, nullptr);
		obs_data_release(audio_settings);
		if (!audio) {
			release_recording();
			error = "recording-audio-encoder-unavailable";
			return false;
		}
		recording_audio.reset(audio);
		obs_encoder_set_audio(recording_audio.value, obs_get_audio());
		obs_data_t *settings = obs_data_create();
		obs_data_set_string(settings, "path", temporary_path.toUtf8().constData());
		obs_data_set_bool(settings, "allow_overwrite", true);
		obs_output_t *output = obs_output_create("ffmpeg_muxer", "WebOBS Program recording",
			settings, nullptr);
		obs_data_release(settings);
		if (!output) {
			release_recording();
			error = "recording-output-unavailable";
			return false;
		}
		recording_output.reset(output);
		obs_output_set_video_encoder(recording_output.value, recording_video.value);
		obs_output_set_audio_encoder(recording_output.value, recording_audio.value, 0);
		if (!obs_output_start(recording_output.value)) {
			const QString detail = bounded_error(obs_output_get_last_error(recording_output.value));
			release_recording();
			recording_error = detail.isEmpty() ? "recording-start-failed"
				: "recording-start-failed: " + detail;
			error = recording_error;
			return false;
		}
		recording = true;
		recording_clock.start();
		recording_bytes = 0;
		return true;
	}
	void remove_partial(QString &error)
	{
		release_recording();
		recording = false;
		QFile::remove(temporary_path);
		recording_error = error;
	}
	bool stop_recording(QString &error)
	{
		if (!recording) {
			if (recording_ready) return true;
			return error = "recording-inactive", false;
		}
		if (recording_output.value) {
			obs_output_stop(recording_output.value);
			if (!wait_output_inactive(recording_output.value, 15000)) {
				obs_output_force_stop(recording_output.value);
				wait_output_inactive(recording_output.value, 5000);
			}
		}
		const qint64 seconds = (recording_clock.elapsed() + 999) / 1000;
		recording_bytes = QFileInfo(temporary_path).size();
		completed_seconds = seconds;
		release_recording();
		recording = false;
		QFileInfo source(temporary_path);
		if (!source.isFile() || source.size() <= 0) {
			error = "recording-empty";
			recording_error = error;
			QFile::remove(temporary_path);
			return false;
		}
		const QString ffmpeg = QDir(runtime_root()).absoluteFilePath("bin/ffmpeg.exe");
		if (!QFileInfo(ffmpeg).isFile()) {
			const QString fallback = final_path.left(final_path.size() - 4) + ".mkv";
			if (QFile::exists(fallback)) QFile::remove(fallback);
			if (!QFile::rename(temporary_path, fallback)) {
				error = "recording-remux-unavailable";
				recording_error = error;
				return false;
			}
			final_path = fallback;
			recording_ready = true;
			recording_error = "recording-remux-unavailable";
			return true;
		}
		QProcess remux;
		remux.setProcessChannelMode(QProcess::MergedChannels);
		remux.start(ffmpeg, {"-hide_banner", "-loglevel", "error", "-y", "-i", temporary_path,
			"-map", "0", "-c", "copy", "-movflags", "+faststart", final_path});
		if (!remux.waitForStarted(5000) || !remux.waitForFinished(120000) ||
		    remux.exitStatus() != QProcess::NormalExit || remux.exitCode() != 0 ||
		    !QFileInfo(final_path).isFile() || QFileInfo(final_path).size() <= 0) {
			error = "recording-remux-failed";
			const QString detail = QString::fromUtf8(remux.readAll()).simplified().left(160);
			recording_error = detail.isEmpty() ? error : error + ": " + detail;
			QFile::remove(final_path);
			return false;
		}
		QFile::remove(temporary_path);
		recording_bytes = QFileInfo(final_path).size();
		recording_ready = true;
		return true;
	}
	bool start_streaming(QString &error)
	{
		if (streaming) return error = "streaming-active", false;
		stream_error.clear();
		if (!start_media_mtx(error)) return false;
		obs_data_t *service_settings = obs_data_create();
		obs_data_set_string(service_settings, "server", stream_publish_url.toUtf8().constData());
		obs_data_set_string(service_settings, "bearer_token", "");
		obs_service_t *service = obs_service_create("whip_custom", "WebOBS Program WHIP",
			service_settings, nullptr);
		obs_data_release(service_settings);
		if (!service) {
			stop_media_mtx();
			error = "stream-service-unavailable";
			return false;
		}
		whip_service.reset(service);
		Data video_settings(obs_data_create());
		obs_data_set_string(video_settings.get(), "rate_control", "CBR");
		obs_data_set_int(video_settings.get(), "bitrate", 6000);
		obs_data_set_int(video_settings.get(), "keyint_sec", 2);
		obs_data_set_string(video_settings.get(), "preset", "veryfast");
		obs_data_set_string(video_settings.get(), "profile", "high");
		obs_service_apply_encoder_settings(whip_service.value, video_settings.get(), nullptr);
		obs_encoder_t *video = obs_video_encoder_create("obs_x264", "WebOBS Program WHIP x264",
			video_settings.get(), nullptr);
		if (!video) {
			release_streaming();
			stop_media_mtx();
			error = "stream-video-encoder-unavailable";
			return false;
		}
		whip_video.reset(video);
		obs_encoder_set_video(whip_video.value, obs_get_video());
		obs_data_t *audio_settings = obs_data_create();
		obs_data_set_int(audio_settings, "bitrate", 96);
		obs_encoder_t *audio = obs_audio_encoder_create("ffmpeg_opus", "WebOBS Program WHIP Opus",
			audio_settings, 0, nullptr);
		obs_data_release(audio_settings);
		if (!audio) {
			release_streaming();
			stop_media_mtx();
			error = "stream-audio-encoder-unavailable";
			return false;
		}
		whip_audio.reset(audio);
		obs_encoder_set_audio(whip_audio.value, obs_get_audio());
		obs_output_t *output = obs_output_create("whip_output", "WebOBS Program WHIP output",
			nullptr, nullptr);
		if (!output) {
			release_streaming();
			stop_media_mtx();
			error = "stream-output-unavailable";
			return false;
		}
		whip_output.reset(output);
		obs_output_set_video_encoder(whip_output.value, whip_video.value);
		obs_output_set_audio_encoder(whip_output.value, whip_audio.value, 0);
		obs_output_set_service(whip_output.value, whip_service.value);
		if (!obs_output_start(whip_output.value)) {
			const QString detail = bounded_error(obs_output_get_last_error(whip_output.value));
			release_streaming();
			stop_media_mtx();
			stream_error = detail.isEmpty() ? "stream-start-failed" : "stream-start-failed: " + detail;
			error = stream_error;
			return false;
		}
		streaming = true;
		stream_clock.start();
		return true;
	}
	bool stop_streaming(QString &error)
	{
		if (!streaming) return error = "streaming-inactive", false;
		if (whip_output.value) {
			obs_output_stop(whip_output.value);
			if (!wait_output_inactive(whip_output.value, 10000)) {
				obs_output_force_stop(whip_output.value);
				wait_output_inactive(whip_output.value, 5000);
			}
		}
		release_streaming();
		streaming = false;
		stop_media_mtx();
		return true;
	}
	void shutdown()
	{
		if (recording) {
			QString ignored;
			stop_recording(ignored);
		}
		if (streaming) {
			QString ignored;
			stop_streaming(ignored);
		}
		stop_media_mtx();
	}
};

ProductProgramOutput::ProductProgramOutput(QString data_root)
	: impl_(std::make_unique<ProductProgramOutputImpl>(std::move(data_root)))
{
}

ProductProgramOutput::~ProductProgramOutput() = default;

bool ProductProgramOutput::start_recording(QString &error)
{
	return impl_->start_recording(error);
}

bool ProductProgramOutput::stop_recording(QString &error)
{
	return impl_->stop_recording(error);
}

bool ProductProgramOutput::start_streaming(QString &error)
{
	return impl_->start_streaming(error);
}

bool ProductProgramOutput::stop_streaming(QString &error)
{
	return impl_->stop_streaming(error);
}

void ProductProgramOutput::shutdown()
{
	impl_->shutdown();
}

ProductProgramOutputStatus ProductProgramOutput::status() const
{
	ProductProgramOutputStatus value;
	value.recording = impl_->recording;
	value.recording_ready = impl_->recording_ready;
	value.recording_path = impl_->final_path;
	value.recording_error = impl_->recording_error;
	value.recording_seconds = impl_->recording ? (impl_->recording_clock.elapsed() + 999) / 1000 :
		impl_->completed_seconds;
	value.recording_bytes = impl_->recording_bytes;
	if (impl_->recording && !impl_->temporary_path.isEmpty()) {
		const qint64 live = QFileInfo(impl_->temporary_path).size();
		if (live > value.recording_bytes) value.recording_bytes = live;
	}
	value.streaming = impl_->streaming;
	value.stream_connected = impl_->streaming && impl_->whip_output.value &&
		obs_output_get_total_frames(impl_->whip_output.value) > 0;
	value.media_mtx_running = impl_->media_mtx.state() == QProcess::Running;
	value.stream_publish_url = impl_->stream_publish_url;
	value.stream_playback_url = impl_->stream_playback_url;
	value.stream_error = impl_->stream_error;
	return value;
}
} // namespace webobs::native_host
