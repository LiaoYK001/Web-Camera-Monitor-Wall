#include "product_output.hpp"

#include <obs.h>

#include <QByteArray>
#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QHostAddress>
#include <QProcess>
#include <QProcessEnvironment>
#include <QSaveFile>
#include <QTcpServer>
#include <QTcpSocket>
#include <QThread>
#include <QUdpSocket>

#include <algorithm>
#include <memory>
#include <utility>
#include <vector>

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

void wait_ms(int milliseconds)
{
	QThread::msleep(static_cast<unsigned long>(milliseconds));
}

QProcessEnvironment child_environment()
{
	QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
	for (const auto &key : environment.keys())
		if (key.startsWith("WEBOBS_"))
			environment.remove(key);
	return environment;
}

bool wait_output_inactive(obs_output_t *output, int timeout_ms)
{
	QElapsedTimer timer;
	timer.start();
	while (obs_output_active(output) && timer.elapsed() < timeout_ms) wait_ms(50);
	return !obs_output_active(output);
}

// An encoded AV output (ffmpeg muxer, RTMP) cannot start with zero audio
// encoders: libobs refuses the start inside can_begin_data_capture() and the
// plugin returns false without ever setting an output-level error. A Scene
// without any routed audio therefore records or publishes one silent track on
// the default bus instead of failing the start for the user.
quint32 encodable_audio_tracks(quint32 selected_tracks)
{
	return selected_tracks ? selected_tracks : 1u;
}

// Name the stage that refused an output start. obs_output_start() can return
// false with an empty last_error, so the receipt must not say only
// "start-failed": the caller gets the concrete preflight reason plus the
// encoder's own error text when libobs copied one.
QString output_preflight_error(obs_output_t *output, const QString &stage,
	const std::vector<obs_encoder_t *> &encoders)
{
	if (!obs_output_can_begin_data_capture(output, 0))
		return stage + QStringLiteral("-capture-not-ready");
	if (obs_output_initialize_encoders(output, 0)) return {};
	QString detail;
	for (auto *encoder : encoders) {
		const QString text = bounded_error(encoder ? obs_encoder_get_last_error(encoder) : nullptr);
		if (!text.isEmpty()) detail = text;
	}
	const QString copied = bounded_error(obs_output_get_last_error(output));
	if (!copied.isEmpty()) detail = copied;
	return detail.isEmpty() ? stage + QStringLiteral("-encoder-initialize-failed")
		: stage + QStringLiteral("-encoder-initialize-failed: ") + detail;
}

QString relay_log_tail(const QByteArray &bytes)
{
	// The relay's own last words are the only evidence of a refusal. Keep them
	// short and neutralize URL markers so a support bundle stays free of URLs.
	QString text = QString::fromUtf8(bytes).simplified().left(240);
	return text.replace(QStringLiteral("://"), QStringLiteral(":/"));
}

QString media_mtx_config(int api_port, int rtsp_port, int webrtc_port, int udp_port, int rtmp_port)
{
	return QStringLiteral(
		// MediaMTX accepts only stdout, file and syslog here; the pinned v1.18.2 relay
		// refused this private config with "invalid log destination: stderr" and exited
		// before opening its API listener, which the host then reported as a timeout.
		"logLevel: warn\n"
		"logDestinations: [stdout]\n"
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
		"rtmp: true\n"
		"rtmpAddress: 127.0.0.1:%5\n"
		"hls: false\n"
		"srt: false\n"
		"webrtc: true\n"
		"webrtcAddress: 127.0.0.1:%3\n"
		"webrtcEncryption: false\n"
		"webrtcAllowOrigins: ['*']\n"
		"webrtcTrustedProxies: []\n"
		"webrtcLocalUDPAddress: 127.0.0.1:%4\n"
		"webrtcLocalTCPAddress: ''\n"
		"webrtcIPsFromInterfaces: false\n"
		"webrtcAdditionalHosts: [127.0.0.1]\n"
		"webrtcICEServers2: []\n"
		"webrtcTrackGatherTimeout: 12s\n"
		"pathDefaults:\n"
		"  source: publisher\n"
		"  overridePublisher: false\n"
		"paths:\n"
		"  program:\n").arg(api_port).arg(rtsp_port).arg(webrtc_port).arg(udp_port).arg(rtmp_port);
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
	QString stream_publish_server;
	QString stream_transport = QStringLiteral("rtmp");
	QString stream_playback_url;
	QString stream_playback_whep;
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
	// One AAC encoder per selected OBS output audio track. Encoder creation has
	// to match obs_source_get_audio_mixers(); a fixed track 0 would record
	// silence whenever the Scene selects another bus.
	Encoder recording_audio[6];
	int recording_audio_count = 0;
	quint32 recording_tracks = 0;
	quint32 streaming_tracks = 0;
	// The mask actually encoded into the retained finished recording.
	quint32 completed_tracks = 0;
	Output publish_output;
	Encoder publish_video;
	Encoder publish_audio;
	Service publish_service;

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
		for (int track = 0; track < 6; ++track)
			recording_audio[track].reset();
		recording_audio_count = 0;
		recording_tracks = 0;
	}
	void release_streaming()
	{
		publish_output.reset();
		publish_video.reset();
		publish_audio.reset();
		publish_service.reset();
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
			stream_error = error = "mediamtx-unavailable";
			return false;
		}
		// Every listener of this private relay is allocated as a free loopback port,
		// including the RTMP publish address. The product's own distribution gateway
		// MediaMTX binds WebRTC on 8889 (gateway/mediamtx.yml), so a fixed publish
		// port made the Program output refuse to start, with an empty streamError,
		// whenever that gateway was running; the publish URL the encoder sends to is
		// derived from the port actually allocated here.
		const int api_port = free_tcp_port();
		int rtsp_port = free_tcp_port();
		while (rtsp_port && rtsp_port == api_port) rtsp_port = free_tcp_port();
		int webrtc_port = free_tcp_port();
		while (webrtc_port && (webrtc_port == api_port || webrtc_port == rtsp_port))
			webrtc_port = free_tcp_port();
		int rtmp_port = free_tcp_port();
		while (rtmp_port && (rtmp_port == api_port || rtmp_port == rtsp_port ||
			rtmp_port == webrtc_port))
			rtmp_port = free_tcp_port();
		const int udp_port = free_udp_port();
		if (!api_port || !rtsp_port || !webrtc_port || !udp_port || !rtmp_port) {
			stream_error = error = "mediamtx-port-failed";
			return false;
		}
		QDir run_dir(QDir(data_root).absoluteFilePath("run/program-output"));
		if (!run_dir.exists() && !QDir().mkpath(run_dir.absolutePath())) {
			stream_error = error = "mediamtx-directory-failed";
			return false;
		}
		const QString config_path = run_dir.absoluteFilePath("mediamtx.yml");
		QSaveFile config(config_path);
		if (!config.open(QIODevice::WriteOnly) ||
		    config.write(media_mtx_config(api_port, rtsp_port, webrtc_port, udp_port,
			    rtmp_port).toUtf8()) < 0 ||
		    !config.commit()) {
			stream_error = error = "mediamtx-config-failed";
			return false;
		}
		media_mtx.setProcessChannelMode(QProcess::MergedChannels);
		media_mtx.setProcessEnvironment(child_environment());
		media_mtx.start(binary, {config_path});
		if (!media_mtx.waitForStarted(5000)) {
			stream_error = error = "mediamtx-start-failed";
			return false;
		}
		// Drain everything the relay writes while waiting: a filled OS pipe would
		// block the child, and its own words are the only evidence of a refusal.
		QByteArray relay_log;
		QElapsedTimer readiness;
		readiness.start();
		while (readiness.elapsed() < 10000) {
			relay_log.append(media_mtx.readAll());
			if (relay_log.size() > 4096)
				relay_log.remove(0, relay_log.size() - 4096);
			// QProcess only notices a child exit through the event loop, and this wait
			// runs inside a UI action, so the process handle is checked directly. An
			// unobserved exit previously turned a refused config into "mediamtx-timeout".
			if (media_mtx.waitForFinished(0)) {
				relay_log.append(media_mtx.readAll());
				const QString detail = relay_log_tail(relay_log);
				stream_error = detail.isEmpty() ? QStringLiteral("mediamtx-exited")
					: QStringLiteral("mediamtx-exited: ") + detail;
				error = QStringLiteral("mediamtx-exited");
				return false;
			}
			QTcpSocket probe;
			probe.connectToHost(QHostAddress::LocalHost, quint16(api_port));
			if (probe.waitForConnected(200)) {
				probe.disconnectFromHost();
				// The publish URL carries no app segment: the relay then takes the
				// stream key ("program") as the whole path name, which is the path it
				// reads back. Verified against the pinned relay: an app segment plus
				// the same key produced "program/program" and closed the publish.
				stream_publish_server =
					QStringLiteral("rtmp://127.0.0.1:%1/").arg(rtmp_port);
				stream_publish_url = stream_publish_server + QStringLiteral("program");
				stream_playback_url =
				QStringLiteral("rtsp://127.0.0.1:%1/program").arg(rtsp_port);
				stream_playback_whep =
					QStringLiteral("http://127.0.0.1:%1/program/whep").arg(webrtc_port);
				return true;
			}
			wait_ms(100);
		}
		relay_log.append(media_mtx.readAll());
		stop_media_mtx();
		relay_log.append(media_mtx.readAll());
		const QString detail = relay_log_tail(relay_log);
		stream_error = error = detail.isEmpty() ? QStringLiteral("mediamtx-timeout")
			: QStringLiteral("mediamtx-timeout: ") + detail;
		return false;
	}
	bool start_recording(QString &error, quint32 audio_tracks)
	{
		if (recording) return error = "recording-active", false;
		recording_error.clear();
		recording_ready = false;
		const quint32 tracks = encodable_audio_tracks(audio_tracks);
		if (!QDir().mkpath(recordings_root)) {
			// The status receipt must carry the same reason the UI shows; a
			// silently refused start would look like an idle product.
			recording_error = error = "recording-directory-failed";
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
			recording_error = error = "recording-encoder-unavailable";
			return false;
		}
		recording_video.reset(video);
		obs_encoder_set_video(recording_video.value, obs_get_video());
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
		// OBS feeds an output from its mixer mask; the default mask delivers only
		// bus 0, which is silent whenever the Scene routes the Program mix to
		// another bus. Declare the buses actually encoded, as the OBS frontend does.
		obs_output_set_mixers(recording_output.value, size_t(tracks));
		obs_output_set_video_encoder(recording_output.value, recording_video.value);
		obs_data_t *audio_settings = obs_data_create();
		obs_data_set_int(audio_settings, "bitrate", 128);
		for (int track = 0; track < 6; ++track) {
			if (!(tracks & (1u << track)))
				continue;
			// Keep the UTF-8 bytes alive in a named QByteArray: the encoder API
			// takes const char *, and a temporary QByteArray would already be gone
			// by the time OBS reads the label.
			const QByteArray label = ("WebOBS Program recording AAC track "
				+ QString::number(track + 1)).toUtf8();
		obs_encoder_t *audio = obs_audio_encoder_create("ffmpeg_aac", label.constData(),
				audio_settings, size_t(track), nullptr);
			if (!audio) {
				obs_data_release(audio_settings);
				release_recording();
				recording_error = error = "recording-audio-encoder-unavailable";
				return false;
			}
			obs_encoder_set_audio(audio, obs_get_audio());
			obs_output_set_audio_encoder(recording_output.value, audio, size_t(recording_audio_count));
			recording_audio[track].reset(audio);
			++recording_audio_count;
		}
		obs_data_release(audio_settings);
		if (recording_audio_count == 0) {
			release_recording();
			error = "recording-audio-encoder-unavailable";
			return false;
		}
		recording_tracks = tracks;
		std::vector<obs_encoder_t *> encoders{recording_video.value};
		for (int track = 0; track < 6; ++track)
			if (recording_audio[track].value)
				encoders.push_back(recording_audio[track].value);
		const QString preflight = output_preflight_error(recording_output.value,
			 QStringLiteral("recording"), encoders);
		if (!preflight.isEmpty()) {
			release_recording();
			recording_error = error = preflight;
			return false;
		}
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
	// Called from the observer path. A user-initiated stop already finalizes the
	// artifact; anything else is an unexpected loss of the OBS output or of the
	// private MediaMTX relay, and the product must stop advertising an output
	// that can no longer deliver frames.
	void refresh()
	{
		if (recording && (!recording_output.value || !obs_output_active(recording_output.value))) {
			const QString detail = bounded_error(obs_output_get_last_error(recording_output.value));
			// remove_partial takes the caller's error by reference, so the reason
			// needs its own named QString instead of a ternary temporary.
			QString reason = detail.isEmpty() ? QStringLiteral("recording-output-lost")
				: QStringLiteral("recording-output-lost: ") + detail;
			remove_partial(reason);
			// No finished artifact exists, so the receipt must not name one.
			final_path.clear();
			recording_bytes = 0;
			return;
		}
		if (!streaming)
			return;
		const bool relay_running = media_mtx.state() == QProcess::Running;
		// The publish output becomes active only after the loopback handshake
		// completes, and a live reconnect is still the same user-facing output, so
		// neither counts as a loss. A dead relay is definitive; a dead output needs
		// the short start window so a slow handshake is not reported as a failure.
		const bool output_live = publish_output.value &&
			(obs_output_active(publish_output.value) || obs_output_reconnecting(publish_output.value));
		if (relay_running && (output_live || stream_clock.elapsed() < 5000))
			return;
		const QString detail = publish_output.value ?
			bounded_error(obs_output_get_last_error(publish_output.value)) : QString();
		if (!relay_running)
			stream_error = detail.isEmpty() ? "publish-relay-exited" : "publish-relay-exited: " + detail;
		else
			stream_error = detail.isEmpty() ? "publish-output-lost" : "publish-output-lost: " + detail;
		release_streaming();
		streaming = false;
		streaming_tracks = 0;
		stop_media_mtx();
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
		// release_recording() drops the encoders, so remember which buses the
		// finished file actually encoded before tearing them down.
		const quint32 encoded_tracks = recording_tracks;
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
			completed_tracks = encoded_tracks;
			recording_error = "recording-remux-unavailable";
			return true;
		}
		QProcess remux;
		remux.setProcessChannelMode(QProcess::MergedChannels);
		remux.setProcessEnvironment(child_environment());
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
		completed_tracks = encoded_tracks;
		return true;
	}
	bool start_streaming(QString &error, quint32 audio_tracks)
	{
		if (streaming) return error = "streaming-active", false;
		stream_error.clear();
		const quint32 tracks = encodable_audio_tracks(audio_tracks);
		if (!start_media_mtx(error)) return false;
		obs_data_t *service_settings = obs_data_create();
		obs_data_set_string(service_settings, "server",
			stream_publish_server.toUtf8().constData());
		obs_data_set_string(service_settings, "key", "program");
		obs_data_set_bool(service_settings, "use_auth", false);
		// The pinned Windows OBS tree builds with -DENABLE_WEBRTC=OFF, so neither
		// whip_custom nor whip_output does: obs-webrtc needs LibDataChannel, which
		// the ABI-locked vcpkg archive does not carry. rtmp_custom and rtmp_output
		// ship in the installed rtmp-services.dll and obs-outputs.dll, and this
		// same private relay republishes the mix as RTSP plus WebRTC/WHEP for a
		// real consumer.
		obs_service_t *service = obs_service_create("rtmp_custom", "WebOBS Program publish",
			service_settings, nullptr);
		obs_data_release(service_settings);
		if (!service) {
			stop_media_mtx();
			stream_error = error = "stream-service-unavailable";
			return false;
		}
		publish_service.reset(service);
		Data video_settings(obs_data_create());
		obs_data_set_string(video_settings.get(), "rate_control", "CBR");
		obs_data_set_int(video_settings.get(), "bitrate", 6000);
		obs_data_set_int(video_settings.get(), "keyint_sec", 2);
		obs_data_set_string(video_settings.get(), "preset", "veryfast");
		obs_data_set_string(video_settings.get(), "profile", "high");
		obs_service_apply_encoder_settings(publish_service.value, video_settings.get(), nullptr);
		obs_encoder_t *video = obs_video_encoder_create("obs_x264", "WebOBS Program publish x264",
			video_settings.get(), nullptr);
		if (!video) {
			release_streaming();
			stop_media_mtx();
			error = "stream-video-encoder-unavailable";
			return false;
		}
		publish_video.reset(video);
		obs_encoder_set_video(publish_video.value, obs_get_video());
		// RTMP/FLV carries one audio track and only accepts AAC. Publish the lowest
		// Program track rather than track 0, which is empty whenever the Scene
		// selects another bus. A Scene with no routed audio publishes a silent bus 0
		// track instead: the encoded publish output cannot start with no audio
		// encoder at all.
		int selected_track = 0;
		for (int track = 0; track < 6; ++track) {
			if (tracks & (1u << track)) {
				selected_track = track;
				break;
			}
		}
		obs_data_t *audio_settings = obs_data_create();
		obs_data_set_int(audio_settings, "bitrate", 128);
		const QByteArray label = ("WebOBS Program publish AAC track "
			+ QString::number(selected_track + 1)).toUtf8();
		obs_encoder_t *audio = obs_audio_encoder_create("ffmpeg_aac", label.constData(),
			audio_settings, size_t(selected_track), nullptr);
		obs_data_release(audio_settings);
		if (!audio) {
			release_streaming();
			stop_media_mtx();
			streaming_tracks = 0;
			error = "stream-audio-encoder-unavailable";
			return false;
		}
		publish_audio.reset(audio);
		obs_encoder_set_audio(publish_audio.value, obs_get_audio());
		obs_output_t *output = obs_output_create("rtmp_output",
			"WebOBS Program publish output", nullptr, nullptr);
		if (!output) {
			release_streaming();
			stop_media_mtx();
			stream_error = error = "stream-output-unavailable";
			return false;
		}
		publish_output.reset(output);
		obs_output_set_mixers(publish_output.value, size_t(1u << selected_track));
		obs_output_set_video_encoder(publish_output.value, publish_video.value);
		obs_output_set_audio_encoder(publish_output.value, publish_audio.value, 0);
		obs_output_set_service(publish_output.value, publish_service.value);
		const QString preflight = output_preflight_error(publish_output.value,
			QStringLiteral("stream"), {publish_video.value, publish_audio.value});
		if (!preflight.isEmpty()) {
			release_streaming();
			stop_media_mtx();
			streaming_tracks = 0;
			stream_error = preflight;
			error = preflight;
			return false;
		}
		if (!obs_output_start(publish_output.value)) {
			const QString detail = bounded_error(obs_output_get_last_error(publish_output.value));
			release_streaming();
			stop_media_mtx();
			stream_error = detail.isEmpty() ? "stream-start-failed" : "stream-start-failed: " + detail;
			error = stream_error;
			return false;
		}
		streaming = true;
		streaming_tracks = tracks;
		stream_clock.start();
		return true;
	}
	bool stop_streaming(QString &error)
	{
		if (!streaming) return error = "streaming-inactive", false;
		if (publish_output.value) {
			obs_output_stop(publish_output.value);
			if (!wait_output_inactive(publish_output.value, 10000)) {
				obs_output_force_stop(publish_output.value);
				wait_output_inactive(publish_output.value, 5000);
			}
		}
		release_streaming();
		streaming = false;
		streaming_tracks = 0;
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

bool ProductProgramOutput::start_recording(QString &error, quint32 audio_tracks)
{
	return impl_->start_recording(error, audio_tracks);
}

bool ProductProgramOutput::stop_recording(QString &error)
{
	return impl_->stop_recording(error);
}

bool ProductProgramOutput::start_streaming(QString &error, quint32 audio_tracks)
{
	return impl_->start_streaming(error, audio_tracks);
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
	impl_->refresh();
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
	value.stream_connected = impl_->streaming && impl_->publish_output.value &&
		obs_output_get_total_frames(impl_->publish_output.value) > 0;
	value.media_mtx_running = impl_->media_mtx.state() == QProcess::Running;
	// While a recording runs this is the mask being encoded; once it finished it
	// stays with the retained file so the receipt can state what the user's MP4
	// actually contains instead of reporting zero after the encoders are gone.
	value.audio_tracks = impl_->recording ? impl_->recording_tracks :
		(impl_->streaming ? impl_->streaming_tracks : impl_->completed_tracks);
	value.stream_publish_url = impl_->stream_publish_url;
	value.stream_playback_url = impl_->stream_playback_url;
	value.stream_playback_whep = impl_->stream_playback_whep;
	value.stream_transport = impl_->stream_transport;
	value.stream_error = impl_->stream_error;
	return value;
}
} // namespace webobs::native_host
