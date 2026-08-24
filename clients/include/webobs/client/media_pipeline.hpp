#pragma once

#include <QObject>
#include <QTimer>

#include <gst/gst.h>

namespace webobs::client {

struct MediaEndpoint {
    QString adapter;
    QString endpoint;
    QString video_codec;
    QString username;
    QString password;
    QString transport = QStringLiteral("tcp");
};

class MediaPipeline final : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString state READ state NOTIFY stateChanged)
    Q_PROPERTY(QString decoder READ decoder NOTIFY diagnosticsChanged)
    Q_PROPERTY(bool hardwareDecode READ hardwareDecode NOTIFY diagnosticsChanged)
    Q_PROPERTY(QString fallbackReason READ fallbackReason NOTIFY diagnosticsChanged)
    Q_PROPERTY(bool recording READ recording NOTIFY recordingChanged)

public:
    explicit MediaPipeline(QObject *parent = nullptr);
    ~MediaPipeline() override;

    static bool initialize(QString &error);
    void set_video_item(QObject *item);
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

signals:
    void stateChanged();
    void diagnosticsChanged();
    void recordingChanged();
    void directReady();
    void directFailed(const QString &reason);

private:
    static void pad_added(GstElement *element, GstPad *pad, gpointer context);
    static void deep_element_added(GstBin *bin, GstBin *sub_bin, GstElement *element,
                                   gpointer context);
    static void first_video_buffer(GstElement *identity, GstBuffer *buffer, gpointer context);
    void set_state(const QString &state);
    void poll_bus();
    void fail(const QString &reason);
    bool build_pipeline(QString &error);
    GstElement *make(const char *factory, const char *name, QString &error);

    MediaEndpoint endpoint_;
    QObject *video_item_ = nullptr;
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
    QString fallback_reason_;
    bool hardware_decode_ = false;
    bool muted_ = true;
};

}
