#include "webobs/client/media_pipeline.hpp"

#include <gst/rtsp/gstrtsptransport.h>

#include <QFileInfo>
#include <QMetaObject>
#include <QRegularExpression>

namespace webobs::client {
namespace {

bool hardware_factory(QString name)
{
    name = name.toLower();
    return name.contains(QStringLiteral("d3d11")) || name.startsWith(QStringLiteral("va")) ||
           name.contains(QStringLiteral("vaapi")) || name.startsWith(QStringLiteral("amc")) ||
           name.contains(QStringLiteral("mediacodec"));
}

QString message_text(GstMessage *message)
{
    GError *native_error = nullptr;
    gchar *debug = nullptr;
    gst_message_parse_error(message, &native_error, &debug);
    const QString result = native_error ? QString::fromUtf8(native_error->message) :
                                          QStringLiteral("GStreamer pipeline failed");
    if (native_error)
        g_error_free(native_error);
    g_free(debug);
    return result;
}

}

MediaPipeline::MediaPipeline(QObject *parent) : QObject(parent)
{
    bus_timer_.setInterval(50);
    connect(&bus_timer_, &QTimer::timeout, this, &MediaPipeline::poll_bus);
    direct_timeout_.setSingleShot(true);
    direct_timeout_.setInterval(3000);
    connect(&direct_timeout_, &QTimer::timeout, this, [this] {
        fail(QStringLiteral("camera_not_reachable_within_three_seconds"));
    });
}

MediaPipeline::~MediaPipeline()
{
    stop();
}

bool MediaPipeline::initialize(QString &error)
{
    GError *native_error = nullptr;
    if (!gst_init_check(nullptr, nullptr, &native_error)) {
        error = native_error ? QString::fromUtf8(native_error->message) :
                               QStringLiteral("GStreamer initialization failed");
        if (native_error)
            g_error_free(native_error);
        return false;
    }
    const QString runtime = QString::fromLatin1(gst_version_string());
#if WEBOBS_LOCKED_RUNTIME
    if (!runtime.contains(QStringLiteral("GStreamer 1.28.6"))) {
        error = QStringLiteral("GStreamer runtime does not match locked version 1.28.6");
        return false;
    }
#endif
    GstRegistry *registry = gst_registry_get();
    GList *features = gst_registry_get_feature_list(registry, GST_TYPE_ELEMENT_FACTORY);
    for (GList *item = features; item; item = item->next) {
        auto *factory = GST_ELEMENT_FACTORY(item->data);
        const QString klass = QString::fromLatin1(gst_element_factory_get_metadata(
            factory, GST_ELEMENT_METADATA_KLASS));
        const QString name = QString::fromLatin1(gst_plugin_feature_get_name(
            GST_PLUGIN_FEATURE(factory)));
        if (klass.contains(QStringLiteral("Decoder/Video")) && hardware_factory(name))
            gst_plugin_feature_set_rank(GST_PLUGIN_FEATURE(factory), GST_RANK_PRIMARY + 100);
    }
    gst_plugin_feature_list_free(features);
    return true;
}

void MediaPipeline::set_video_item(QObject *item)
{
    video_item_ = item;
    if (video_sink_)
        g_object_set(video_sink_, "widget", video_item_.data(), nullptr);
}

GstElement *MediaPipeline::make(const char *factory, const char *name, QString &error)
{
    GstElement *element = gst_element_factory_make(factory, name);
    if (!element)
        error = QStringLiteral("required GStreamer element is unavailable: %1").arg(factory);
    return element;
}

bool MediaPipeline::build_pipeline(QString &error)
{
    pipeline_ = gst_pipeline_new("webobs-true-direct");
    if (!pipeline_) {
        error = QStringLiteral("GStreamer pipeline allocation failed");
        return false;
    }
    const QString adapter = endpoint_.adapter.toLower();
    const bool uri_decoder = adapter == QStringLiteral("mjpeg") || adapter == QStringLiteral("hls");
    if (adapter == QStringLiteral("rtsp")) {
        source_ = make("rtspsrc", "directSource", error);
        decoder_bin_ = make("decodebin3", "directDecoder", error);
        if (!source_ || !decoder_bin_)
            return false;
        g_object_set(source_, "location", endpoint_.endpoint.toUtf8().constData(),
                     "protocols", endpoint_.transport == QStringLiteral("udp") ?
                         GST_RTSP_LOWER_TRANS_UDP : GST_RTSP_LOWER_TRANS_TCP,
                     "latency", 150u, "timeout", static_cast<guint64>(3'000'000), nullptr);
        if (!endpoint_.username.isEmpty())
            g_object_set(source_, "user-id", endpoint_.username.toUtf8().constData(),
                         "user-pw", endpoint_.password.toUtf8().constData(), nullptr);
    } else if (uri_decoder) {
        source_ = make("uridecodebin3", "directSource", error);
        if (!source_)
            return false;
        g_object_set(source_, "uri", endpoint_.endpoint.toUtf8().constData(), nullptr);
    } else if (adapter == QStringLiteral("whep")) {
        source_ = make("whepclientsrc", "directSource", error);
        decoder_bin_ = make("decodebin3", "directDecoder", error);
        if (!source_ || !decoder_bin_)
            return false;
        g_object_set(source_, "whep-endpoint", endpoint_.endpoint.toUtf8().constData(), nullptr);
    } else {
        error = QStringLiteral("unsupported True Direct protocol adapter");
        return false;
    }

    video_convert_ = make("videoconvert", "videoConvert", error);
    video_probe_ = make("identity", "firstVideoBuffer", error);
    video_sink_ = make(video_item_ ? "qml6glsink" : "fakesink", "videoSink", error);
    audio_convert_ = make("audioconvert", "audioConvert", error);
    audio_resample_ = make("audioresample", "audioResample", error);
    audio_volume_ = make("volume", "audioVolume", error);
    audio_sink_ = make(video_item_ ? "autoaudiosink" : "fakesink", "audioSink", error);
    if (!video_convert_ || !video_probe_ || !video_sink_ || !audio_convert_ ||
        !audio_resample_ || !audio_volume_ || !audio_sink_)
        return false;
    g_object_set(video_probe_, "silent", true, nullptr);
    g_object_set(audio_volume_, "mute", muted_, nullptr);
    // Some camera profiles are video-only.  Keep the optional, currently
    // unlinked audio branch from participating in the pipeline preroll or a
    // valid video stream can remain in ASYNC forever waiting for audio.
    g_object_set(audio_sink_, "async", false, nullptr);
    if (!video_item_)
        g_object_set(audio_sink_, "sync", false, nullptr);
    if (video_item_)
        g_object_set(video_sink_, "widget", video_item_.data(), nullptr);

    gst_bin_add(GST_BIN(pipeline_), source_);
    if (decoder_bin_)
        gst_bin_add(GST_BIN(pipeline_), decoder_bin_);
    gst_bin_add_many(GST_BIN(pipeline_), video_convert_, video_probe_, video_sink_, audio_convert_,
                     audio_resample_, audio_volume_, audio_sink_, nullptr);
    if (!gst_element_link_many(video_convert_, video_probe_, video_sink_, nullptr) ||
        !gst_element_link_many(audio_convert_, audio_resample_, audio_volume_, audio_sink_, nullptr)) {
        error = QStringLiteral("GStreamer output elements could not be linked");
        return false;
    }
    g_signal_connect(source_, "pad-added", G_CALLBACK(&MediaPipeline::pad_added), this);
    if (decoder_bin_) {
        g_signal_connect(decoder_bin_, "pad-added", G_CALLBACK(&MediaPipeline::pad_added), this);
        g_signal_connect(decoder_bin_, "deep-element-added",
                         G_CALLBACK(&MediaPipeline::deep_element_added), this);
    } else {
        g_signal_connect(source_, "deep-element-added",
                         G_CALLBACK(&MediaPipeline::deep_element_added), this);
    }
    g_signal_connect(pipeline_, "deep-element-added",
                     G_CALLBACK(&MediaPipeline::deep_element_added), this);
    GstPad *probe_pad = gst_element_get_static_pad(video_probe_, "src");
    if (!probe_pad) {
        error = QStringLiteral("video diagnostics pad is unavailable");
        return false;
    }
    gst_pad_add_probe(probe_pad, GST_PAD_PROBE_TYPE_BUFFER,
                      &MediaPipeline::video_buffer_probe, this, nullptr);
    gst_object_unref(probe_pad);
    return true;
}

bool MediaPipeline::start(const MediaEndpoint &endpoint, QString &error)
{
    stop();
    endpoint_ = endpoint;
    fallback_reason_.clear();
    decoder_ = QStringLiteral("discovering");
    hardware_decode_ = false;
    frames_decoded_.store(0, std::memory_order_relaxed);
    frames_dropped_.store(0, std::memory_order_relaxed);
    current_fps_ = 0;
    if (!build_pipeline(error)) {
        stop();
        return false;
    }
    set_state(QStringLiteral("probing"));
    const GstStateChangeReturn result = gst_element_set_state(pipeline_, GST_STATE_PLAYING);
    if (result == GST_STATE_CHANGE_FAILURE) {
        error = QStringLiteral("GStreamer rejected the direct pipeline");
        stop();
        return false;
    }
    bus_timer_.start();
    if (!statistics_clock_.isValid())
        statistics_clock_.start();
    else
        statistics_clock_.restart();
    last_reported_frames_ = frames_decoded_.load(std::memory_order_relaxed);
    direct_timeout_.start();
    return true;
}

void MediaPipeline::stop()
{
    direct_timeout_.stop();
    bus_timer_.stop();
    stopRecording();
    if (pipeline_) {
        gst_element_set_state(pipeline_, GST_STATE_NULL);
        gst_object_unref(pipeline_);
    }
    pipeline_ = source_ = decoder_bin_ = video_convert_ = video_probe_ = video_sink_ = nullptr;
    audio_convert_ = audio_resample_ = audio_volume_ = audio_sink_ = nullptr;
    if (state_ != QStringLiteral("failed"))
        set_state(QStringLiteral("idle"));
}

void MediaPipeline::pad_added(GstElement *element, GstPad *pad, gpointer context)
{
    auto *self = static_cast<MediaPipeline *>(context);
    GstCaps *caps = gst_pad_get_current_caps(pad);
    if (!caps)
        caps = gst_pad_query_caps(pad, nullptr);
    const GstStructure *structure = caps && gst_caps_get_size(caps) ? gst_caps_get_structure(caps, 0) : nullptr;
    const QString type = structure ? QString::fromLatin1(gst_structure_get_name(structure)) : QString{};
    GstElement *target = nullptr;
    if (type.startsWith(QStringLiteral("video/")))
        target = self->video_convert_;
    else if (type.startsWith(QStringLiteral("audio/")))
        target = self->audio_convert_;
    else if ((type == QStringLiteral("application/x-rtp") || type.startsWith(QStringLiteral("application/"))) &&
             element == self->source_)
        target = self->decoder_bin_;
    if (target) {
        GstPad *sink = gst_element_get_static_pad(target, "sink");
        if (sink && !gst_pad_is_linked(sink))
            gst_pad_link(pad, sink);
        if (sink)
            gst_object_unref(sink);
    }
    if (caps)
        gst_caps_unref(caps);
}

void MediaPipeline::deep_element_added(GstBin *, GstBin *, GstElement *element, gpointer context)
{
    auto *self = static_cast<MediaPipeline *>(context);
    GstElementFactory *factory = gst_element_get_factory(element);
    if (!factory)
        return;
    const QString klass = QString::fromLatin1(gst_element_factory_get_metadata(
        factory, GST_ELEMENT_METADATA_KLASS));
    if (!klass.contains(QStringLiteral("Decoder/Video")))
        return;
    self->decoder_factory_ = QString::fromLatin1(
        gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory)));
    self->decoder_ = QString::fromLatin1(GST_OBJECT_NAME(element));
    self->hardware_decode_ = hardware_factory(self->decoder_factory_);
    self->fallback_reason_ = self->hardware_decode_ ? QString{} :
        QStringLiteral("hardware_decoder_unavailable");
    QMetaObject::invokeMethod(self, [self] { emit self->diagnosticsChanged(); }, Qt::QueuedConnection);
}

GstPadProbeReturn MediaPipeline::video_buffer_probe(GstPad *, GstPadProbeInfo *info,
                                                    gpointer context)
{
    auto *self = static_cast<MediaPipeline *>(context);
    if (!GST_PAD_PROBE_INFO_BUFFER(info))
        return GST_PAD_PROBE_OK;
    const quint64 previous = self->frames_decoded_.fetch_add(1, std::memory_order_relaxed);
    if (previous != 0)
        return GST_PAD_PROBE_OK;
    QMetaObject::invokeMethod(self, [self] {
        if (self->state_ != QStringLiteral("probing"))
            return;
        self->direct_timeout_.stop();
        self->set_state(QStringLiteral("playing"));
        emit self->directReady();
    }, Qt::QueuedConnection);
    return GST_PAD_PROBE_OK;
}

void MediaPipeline::poll_bus()
{
    if (!pipeline_)
        return;
    GstBus *bus = gst_element_get_bus(pipeline_);
    while (GstMessage *message = gst_bus_pop(bus)) {
        switch (GST_MESSAGE_TYPE(message)) {
        case GST_MESSAGE_ERROR: {
            GstElement *origin = GST_IS_ELEMENT(GST_MESSAGE_SRC(message)) ?
                GST_ELEMENT(GST_MESSAGE_SRC(message)) : nullptr;
            GstElementFactory *origin_factory = origin ? gst_element_get_factory(origin) : nullptr;
            const QString origin_name = origin_factory ? QString::fromLatin1(
                gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(origin_factory))) : QString{};
            if (!software_fallback_forced_ && hardware_decode_ &&
                (hardware_factory(origin_name) || origin_name == decoder_factory_)) {
                GstPluginFeature *feature = gst_registry_find_feature(
                    gst_registry_get(), decoder_factory_.toUtf8().constData(),
                    GST_TYPE_ELEMENT_FACTORY);
                if (feature) {
                    gst_plugin_feature_set_rank(feature, GST_RANK_NONE);
                    gst_object_unref(feature);
                }
                software_fallback_forced_ = true;
                fail(QStringLiteral("hardware_decoder_failed_software_fallback"));
            } else {
                fail(message_text(message));
            }
            break;
        }
        case GST_MESSAGE_ASYNC_DONE:
            break;
        case GST_MESSAGE_EOS:
            fail(QStringLiteral("camera_stream_ended"));
            break;
        case GST_MESSAGE_QOS: {
            GstFormat format = GST_FORMAT_UNDEFINED;
            guint64 processed = 0;
            guint64 dropped = 0;
            gst_message_parse_qos_stats(message, &format, &processed, &dropped);
            if (format == GST_FORMAT_BUFFERS) {
                quint64 observed = frames_dropped_.load(std::memory_order_relaxed);
                while (dropped > observed && !frames_dropped_.compare_exchange_weak(
                    observed, dropped, std::memory_order_relaxed)) {}
            }
            break;
        }
        default:
            break;
        }
        gst_message_unref(message);
        if (!pipeline_)
            break;
    }
    gst_object_unref(bus);
    if (statistics_clock_.isValid() && statistics_clock_.elapsed() >= 1000) {
        const quint64 current = frames_decoded_.load(std::memory_order_relaxed);
        const qint64 elapsed = statistics_clock_.restart();
        current_fps_ = elapsed > 0 ? 1000.0 * static_cast<double>(current - last_reported_frames_) /
                                     static_cast<double>(elapsed) : 0.0;
        last_reported_frames_ = current;
        emit statisticsChanged();
    }
}

void MediaPipeline::fail(const QString &reason)
{
    if (state_ == QStringLiteral("failed"))
        return;
    QString sanitized = reason;
    if (!endpoint_.endpoint.isEmpty())
        sanitized.replace(endpoint_.endpoint, QStringLiteral("<redacted-media-endpoint>"));
    sanitized.replace(QRegularExpression(
        QStringLiteral(R"(([A-Za-z][A-Za-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@)")),
        QStringLiteral("\\1***:***@"));
    sanitized.replace(QRegularExpression(
        QStringLiteral(R"(([?&](?:token|access_token|password|key|sig)=)[^&#\s]+)"),
        QRegularExpression::CaseInsensitiveOption), QStringLiteral("\\1***"));
    fallback_reason_ = sanitized.left(256);
    set_state(QStringLiteral("failed"));
    emit diagnosticsChanged();
    emit directFailed(fallback_reason_);
    direct_timeout_.stop();
    if (pipeline_)
        gst_element_set_state(pipeline_, GST_STATE_NULL);
}

bool MediaPipeline::start_recording(const QString &path, QString &error)
{
    if (recording_pipeline_) {
        error = QStringLiteral("manual recording is already active");
        return false;
    }
    if (endpoint_.adapter != QStringLiteral("rtsp") ||
        (endpoint_.video_codec != QStringLiteral("h264") && endpoint_.video_codec != QStringLiteral("h265"))) {
        error = QStringLiteral("stream-copy recording currently requires RTSP H.264/H.265");
        return false;
    }
    if (!QFileInfo(path).isAbsolute() || !path.endsWith(QStringLiteral(".mkv"), Qt::CaseInsensitive)) {
        error = QStringLiteral("manual recordings require an absolute .mkv path");
        return false;
    }
    recording_pipeline_ = gst_pipeline_new("webobs-manual-recording");
    GstElement *source = gst_element_factory_make("rtspsrc", "recordSource");
    GstElement *depay = gst_element_factory_make(
        endpoint_.video_codec == QStringLiteral("h264") ? "rtph264depay" : "rtph265depay", "depay");
    GstElement *parser = gst_element_factory_make(
        endpoint_.video_codec == QStringLiteral("h264") ? "h264parse" : "h265parse", "parser");
    GstElement *muxer = gst_element_factory_make("matroskamux", "muxer");
    GstElement *sink = gst_element_factory_make("filesink", "recordSink");
    if (!recording_pipeline_ || !source || !depay || !parser || !muxer || !sink) {
        error = QStringLiteral("stream-copy recording elements are unavailable");
        stopRecording();
        return false;
    }
    g_object_set(source, "location", endpoint_.endpoint.toUtf8().constData(),
                 "protocols", endpoint_.transport == QStringLiteral("udp") ?
                     GST_RTSP_LOWER_TRANS_UDP : GST_RTSP_LOWER_TRANS_TCP, nullptr);
    if (!endpoint_.username.isEmpty())
        g_object_set(source, "user-id", endpoint_.username.toUtf8().constData(),
                     "user-pw", endpoint_.password.toUtf8().constData(), nullptr);
    g_object_set(parser, "config-interval", -1, nullptr);
    g_object_set(sink, "location", path.toUtf8().constData(), "sync", false, nullptr);
    gst_bin_add_many(GST_BIN(recording_pipeline_), source, depay, parser, muxer, sink, nullptr);
    if (!gst_element_link_many(depay, parser, muxer, sink, nullptr)) {
        error = QStringLiteral("stream-copy recording pipeline could not be linked");
        stopRecording();
        return false;
    }
    g_signal_connect(source, "pad-added", G_CALLBACK(+[](GstElement *, GstPad *pad, gpointer target) {
        GstCaps *caps = gst_pad_get_current_caps(pad);
        if (!caps)
            caps = gst_pad_query_caps(pad, nullptr);
        const GstStructure *structure = caps && gst_caps_get_size(caps) > 0 ?
            gst_caps_get_structure(caps, 0) : nullptr;
        const gchar *media = structure ? gst_structure_get_string(structure, "media") : nullptr;
        if (!media || g_strcmp0(media, "video") != 0) {
            if (caps)
                gst_caps_unref(caps);
            return;
        }
        if (caps)
            gst_caps_unref(caps);
        GstPad *sink_pad = gst_element_get_static_pad(GST_ELEMENT(target), "sink");
        if (sink_pad && !gst_pad_is_linked(sink_pad))
            gst_pad_link(pad, sink_pad);
        if (sink_pad)
            gst_object_unref(sink_pad);
    }), depay);
    if (gst_element_set_state(recording_pipeline_, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
        error = QStringLiteral("stream-copy recording could not start");
        stopRecording();
        return false;
    }
    emit recordingChanged();
    return true;
}

void MediaPipeline::stopRecording()
{
    if (!recording_pipeline_)
        return;
    gst_element_send_event(recording_pipeline_, gst_event_new_eos());
    GstBus *bus = gst_element_get_bus(recording_pipeline_);
    GstMessage *message = gst_bus_timed_pop_filtered(bus, 3 * GST_SECOND,
        static_cast<GstMessageType>(GST_MESSAGE_EOS | GST_MESSAGE_ERROR));
    if (message)
        gst_message_unref(message);
    gst_object_unref(bus);
    gst_element_set_state(recording_pipeline_, GST_STATE_NULL);
    gst_object_unref(recording_pipeline_);
    recording_pipeline_ = nullptr;
    emit recordingChanged();
}

void MediaPipeline::set_muted(bool muted)
{
    if (muted_ == muted)
        return;
    muted_ = muted;
    if (audio_volume_)
        g_object_set(audio_volume_, "mute", muted_, nullptr);
    emit mutedChanged();
}

void MediaPipeline::set_state(const QString &state)
{
    if (state_ == state)
        return;
    state_ = state;
    emit stateChanged();
}

QString MediaPipeline::state() const { return state_; }
QString MediaPipeline::decoder() const { return decoder_; }
bool MediaPipeline::hardwareDecode() const { return hardware_decode_; }
QString MediaPipeline::fallbackReason() const { return fallback_reason_; }
bool MediaPipeline::recording() const { return recording_pipeline_ != nullptr; }
bool MediaPipeline::muted() const { return muted_; }
quint64 MediaPipeline::framesDecoded() const { return frames_decoded_.load(std::memory_order_relaxed); }
quint64 MediaPipeline::framesDropped() const { return frames_dropped_.load(std::memory_order_relaxed); }
double MediaPipeline::currentFps() const { return current_fps_; }

}
