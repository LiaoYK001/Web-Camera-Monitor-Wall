#pragma once

#include <QString>

#include <cstdint>
#include <memory>

namespace webobs::native_host {
struct ProductProgramOutputStatus {
	bool recording = false;
	bool recording_ready = false;
	QString recording_path;
	QString recording_error;
	qint64 recording_bytes = 0;
	qint64 recording_seconds = 0;
	bool streaming = false;
	bool stream_connected = false;
	bool media_mtx_running = false;
	// OBS output audio-track mask the active output actually encodes. Zero means
	// the applied Program carries no audio, so the file/stream is video only.
	quint32 audio_tracks = 0;
	QString stream_publish_url;
	QString stream_playback_url;
	// Browser-readable playback of the same mix (WebRTC/WHEP on the private
	// relay). It is informational: the gate decodes the RTSP playback.
	QString stream_playback_whep;
	// Transport the publish output actually uses. The pinned Windows OBS tree
	// builds with -DENABLE_WEBRTC=OFF, so this is "rtmp", not "whip".
	QString stream_transport;
	QString stream_error;
};

// Owns OBS Program encoders, one optional file output and one optional
// publish output. The local monitor/preview path never depends on this object, so an
// idle product starts no encoder, no MediaMTX and no transcoder. Main thread
// only, like the rest of the native product window.
class ProductProgramOutput {
	std::unique_ptr<class ProductProgramOutputImpl> impl_;
public:
	explicit ProductProgramOutput(QString data_root);
	~ProductProgramOutput();
	ProductProgramOutput(const ProductProgramOutput &) = delete;
	ProductProgramOutput &operator=(const ProductProgramOutput &) = delete;

	// audio_tracks is the OBS output audio-track mask of the applied Program
	// scene. Encoders are created for exactly those tracks; an encoder pinned to
	// track 0 would record or publish silence whenever a Scene selects another
	// track while the meter still shows a signal.
	bool start_recording(QString &error, quint32 audio_tracks);
	bool stop_recording(QString &error);
	bool start_streaming(QString &error, quint32 audio_tracks);
	bool stop_streaming(QString &error);
	void shutdown();
	ProductProgramOutputStatus status() const;
};
} // namespace webobs::native_host
