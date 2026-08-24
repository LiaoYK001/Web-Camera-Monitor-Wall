#pragma once

#include <QByteArray>
#include <QMutex>
#include <QObject>
#include <QTimer>

#include <gst/gst.h>

namespace webobs::client {

class TalkCapture final : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool active READ active NOTIFY activeChanged)

public:
    explicit TalkCapture(QObject *parent = nullptr);
    ~TalkCapture() override;

    bool start(QString &error);
    void finish();
    void cancel();
    [[nodiscard]] bool active() const;

signals:
    void activeChanged();
    void captured(const QByteArray &wav);
    void failed(const QString &message);

private:
    static GstFlowReturn new_sample(GstElement *sink, gpointer context);
    void stop(bool deliver);

    GstElement *pipeline_ = nullptr;
    GstElement *sink_ = nullptr;
    QTimer maximum_duration_;
    mutable QMutex mutex_;
    QByteArray audio_;
    bool overflow_ = false;
};

}
