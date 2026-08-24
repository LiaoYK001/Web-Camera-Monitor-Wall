#include "webobs/client/talk_capture.hpp"

#include <gst/app/gstappsink.h>

#include <QMutexLocker>

namespace webobs::client {
namespace {
constexpr qsizetype maximum_talk_bytes = 1024 * 1024;
}

TalkCapture::TalkCapture(QObject *parent) : QObject(parent)
{
    maximum_duration_.setSingleShot(true);
    maximum_duration_.setInterval(10'000);
    connect(&maximum_duration_, &QTimer::timeout, this, &TalkCapture::finish);
}

TalkCapture::~TalkCapture()
{
    cancel();
}

bool TalkCapture::start(QString &error)
{
    if (pipeline_) {
        error = QStringLiteral("Push-to-Talk capture is already active");
        return false;
    }
    GError *native_error = nullptr;
    pipeline_ = gst_parse_launch(
        "autoaudiosrc ! audioconvert ! audioresample ! "
        "audio/x-raw,format=S16LE,rate=16000,channels=1 ! wavenc ! "
        "appsink name=talkSink emit-signals=true sync=false max-buffers=64 drop=false",
        &native_error);
    if (!pipeline_) {
        error = native_error ? QString::fromUtf8(native_error->message) :
                               QStringLiteral("Microphone capture pipeline is unavailable");
        if (native_error)
            g_error_free(native_error);
        return false;
    }
    sink_ = gst_bin_get_by_name(GST_BIN(pipeline_), "talkSink");
    if (!sink_) {
        error = QStringLiteral("Microphone capture sink is unavailable");
        cancel();
        return false;
    }
    {
        QMutexLocker lock(&mutex_);
        audio_.clear();
        overflow_ = false;
    }
    g_signal_connect(sink_, "new-sample", G_CALLBACK(&TalkCapture::new_sample), this);
    if (gst_element_set_state(pipeline_, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
        error = QStringLiteral("Microphone permission was denied or capture could not start");
        cancel();
        return false;
    }
    maximum_duration_.start();
    emit activeChanged();
    return true;
}

GstFlowReturn TalkCapture::new_sample(GstElement *sink, gpointer context)
{
    auto *self = static_cast<TalkCapture *>(context);
    GstSample *sample = gst_app_sink_pull_sample(GST_APP_SINK(sink));
    if (!sample)
        return GST_FLOW_EOS;
    GstBuffer *buffer = gst_sample_get_buffer(sample);
    GstMapInfo map{};
    bool overflow = false;
    if (buffer && gst_buffer_map(buffer, &map, GST_MAP_READ)) {
        QMutexLocker lock(&self->mutex_);
        const qsizetype bytes = static_cast<qsizetype>(map.size);
        if (!self->overflow_ && bytes >= 0 && self->audio_.size() <= maximum_talk_bytes - bytes)
            self->audio_.append(reinterpret_cast<const char *>(map.data), bytes);
        else
            self->overflow_ = true;
        overflow = self->overflow_;
        gst_buffer_unmap(buffer, &map);
    }
    gst_sample_unref(sample);
    return overflow ? GST_FLOW_ERROR : GST_FLOW_OK;
}

void TalkCapture::finish() { stop(true); }
void TalkCapture::cancel() { stop(false); }

void TalkCapture::stop(bool deliver)
{
    maximum_duration_.stop();
    if (!pipeline_)
        return;
    gst_element_send_event(pipeline_, gst_event_new_eos());
    GstBus *bus = gst_element_get_bus(pipeline_);
    GstMessage *message = gst_bus_timed_pop_filtered(bus, GST_SECOND,
        static_cast<GstMessageType>(GST_MESSAGE_EOS | GST_MESSAGE_ERROR));
    if (message)
        gst_message_unref(message);
    gst_object_unref(bus);
    gst_element_set_state(pipeline_, GST_STATE_NULL);
    if (sink_) {
        gst_object_unref(sink_);
        sink_ = nullptr;
    }
    gst_object_unref(pipeline_);
    pipeline_ = nullptr;
    QByteArray captured_audio;
    bool overflow = false;
    {
        QMutexLocker lock(&mutex_);
        captured_audio = std::move(audio_);
        audio_.clear();
        overflow = overflow_;
        overflow_ = false;
    }
    emit activeChanged();
    if (!deliver)
        return;
    if (overflow || captured_audio.size() < 44) {
        emit failed(overflow ? QStringLiteral("Push-to-Talk audio exceeded its safe limit") :
                               QStringLiteral("Push-to-Talk captured no audio"));
        return;
    }
    emit captured(captured_audio);
}

bool TalkCapture::active() const { return pipeline_ != nullptr; }

}
