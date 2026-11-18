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
	QString stream_publish_url;
	QString stream_playback_url;
	QString stream_error;
};

// Owns OBS Program encoders, one optional file output and one optional WHIP
// output. The local monitor/preview path never depends on this object, so an
// idle product starts no encoder, no MediaMTX and no transcoder. Main thread
// only, like the rest of the native product window.
class ProductProgramOutput {
	std::unique_ptr<class ProductProgramOutputImpl> impl_;
public:
	explicit ProductProgramOutput(QString data_root);
	~ProductProgramOutput();
	ProductProgramOutput(const ProductProgramOutput &) = delete;
	ProductProgramOutput &operator=(const ProductProgramOutput &) = delete;

	bool start_recording(QString &error);
	bool stop_recording(QString &error);
	bool start_streaming(QString &error);
	bool stop_streaming(QString &error);
	void shutdown();
	ProductProgramOutputStatus status() const;
};
} // namespace webobs::native_host
