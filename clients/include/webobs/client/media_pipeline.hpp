#pragma once

#include <QObject>
#include <QElapsedTimer>
#include <QPointer>
#include <QTimer>

#include <gst/gst.h>

#include <atomic>

namespace webobs::client {

struct MediaEndpoint {
    QString adapter;
    QString endpoint;
    QString video_codec;
    QString audio_codec;
    QString username;
    QString password;
    QString bearer_token;
    QString transport = QStringLiteral("tcp");
};

class MediaPipeline final : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString state READ state NOTIFY stateChanged)
    Q_PROPERTY(QString decoder READ decoder NOTIFY diagnosticsChanged)
    Q_PROPERTY(bool hardwareDecode READ hardwareDecode NOTIFY diagnosticsChanged)
    Q_PROPERTY(QString fallbackReason READ fallbackReason NOTIFY diagnosticsChanged)
    Q_PROPERTY(bool recording READ recording NOTIFY recordingChanged)
    Q_PROPERTY(bool muted READ muted NOTIFY mutedChanged)
    Q_PROPERTY(quint64 framesDecoded READ framesDecoded NOTIFY statisticsChanged)
    Q_PROPERTY(quint64 framesDropped READ framesDropped NOTIFY statisticsChanged)
    Q_PROPERTY(double currentFps READ currentFps NOTIFY statisticsChanged)
    Q_PROPERTY(int videoWidth READ videoWidth NOTIFY statisticsChanged)
    Q_PROPERTY(int videoHeight READ videoHeight NOTIFY statisticsChanged)
    Q_PROPERTY(quint64 visualSamples READ visualSamples NOTIFY statisticsChanged)
    Q_PROPERTY(quint64 blackSamples READ blackSamples NOTIFY statisticsChanged)
    Q_PROPERTY(quint64 pipelineRestarts READ pipelineRestarts NOTIFY statisticsChanged)

public:
    explicit MediaPipeline(QObject *parent = nullptr);
    ~MediaPipeline() override;

    static bool initialize(QString &error);
    void set_video_item(QObject *item);
    Q_INVOKABLE void setVideoItem(QObject *item) { set_video_item(item); }
    bool start(const MediaEndpoint &endpoint, QString &error);
    Q_INVOKABLE void stop();
    bool start_recording(const QString &path, QString &error);
    Q_INVOKABLE void stopRecording();
    void set_muted(bool muted);

    [[nodiscard]] QString state() const;
    [[nodiscard]] QString decoder() const;
    [[nodiscard]] bool hardwareDecode() const;
    [[nodiscard]] QString fallbackReason() const;
    [[nodiscard]] bool recording() const;
    [[nodiscard]] bool muted() const;
    [[nodiscard]] quint64 framesDecoded() const;
    [[nodiscard]] quint64 framesDropped() const;
    [[nodiscard]] double currentFps() const;
    [[nodiscard]] int videoWidth() const;
    [[nodiscard]] int videoHeight() const;
    [[nodiscard]] quint64 visualSamples() const;
    [[nodiscard]] quint64 blackSamples() const;
    [[nodiscard]] quint64 pipelineRestarts() const;

signals:
    void stateChanged();
    void diagnosticsChanged();
    void recordingChanged();
    void mutedChanged();
    void statisticsChanged();
    void directReady();
    void directFailed(const QString &reason);

private:
    static void pad_added(GstElement *element, GstPad *pad, gpointer context);
    static void deep_element_added(GstBin *bin, GstBin *sub_bin, GstElement *element,
                                   gpointer context);
    static GstPadProbeReturn video_buffer_probe(GstPad *pad, GstPadProbeInfo *info,
                                                gpointer context);
    void set_state(const QString &state);
    void poll_bus();
    void fail(const QString &reason);
    void restart_with_software_fallback();
    void restore_failed_hardware_rank();
    bool build_pipeline(QString &error);
    GstElement *make(const char *factory, const char *name, QString &error);

    MediaEndpoint endpoint_;
    QPointer<QObject> video_item_;
    GstElement *pipeline_ = nullptr;
    GstElement *source_ = nullptr;
    GstElement *decoder_bin_ = nullptr;
    GstElement *video_convert_ = nullptr;
    GstElement *video_probe_ = nullptr;
    GstElement *video_sink_ = nullptr;
    GstElement *audio_convert_ = nullptr;
    GstElement *audio_resample_ = nullptr;
    GstElement *audio_volume_ = nullptr;
    GstElement *audio_sink_ = nullptr;
    GstElement *recording_pipeline_ = nullptr;
    QTimer bus_timer_;
    QTimer direct_timeout_;
    QString state_ = QStringLiteral("idle");
    QString decoder_ = QStringLiteral("not-started");
    QString decoder_factory_;
    QString failed_hardware_factory_;
    QString fallback_reason_;
    bool hardware_decode_ = false;
    bool software_fallback_forced_ = false;
    bool muted_ = true;
    std::atomic<quint64> frames_decoded_{0};
    std::atomic<quint64> frames_dropped_{0};
    QElapsedTimer statistics_clock_;
    quint64 last_reported_frames_ = 0;
    double current_fps_ = 0;
    std::atomic<int> video_width_{0};
    std::atomic<int> video_height_{0};
    std::atomic<quint64> visual_samples_{0};
    std::atomic<quint64> black_samples_{0};
    std::atomic<quint64> pipeline_restarts_{0};
};

}
