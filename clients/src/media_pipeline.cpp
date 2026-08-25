#include "webobs/client/media_pipeline.hpp"

#include <gst/rtsp/gstrtsptransport.h>
#include <gst/video/video.h>

#include <QFileInfo>
#include <QHash>
#include <QMetaObject>
#include <QMutex>
#include <QMutexLocker>
#include <QRegularExpression>

#if defined(Q_OS_ANDROID)
GST_PLUGIN_STATIC_DECLARE(qml6);
#endif

#include <algorithm>
#include <optional>

namespace webobs::client {
namespace {

struct RankHold {
    guint original_rank = GST_RANK_NONE;
    int holders = 0;
};

QMutex rank_hold_mutex;
QHash<QString, RankHold> rank_holds;

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

bool hold_hardware_rank(const QString &factory_name)
{
    QMutexLocker locker(&rank_hold_mutex);
    auto existing = rank_holds.find(factory_name);
    if (existing != rank_holds.end()) {
        ++existing->holders;
        return true;
    }
    GstPluginFeature *feature = gst_registry_find_feature(
        gst_registry_get(), factory_name.toUtf8().constData(), GST_TYPE_ELEMENT_FACTORY);
    if (!feature)
        return false;
    RankHold hold{gst_plugin_feature_get_rank(feature), 1};
    gst_plugin_feature_set_rank(feature, GST_RANK_NONE);
    gst_object_unref(feature);
    rank_holds.insert(factory_name, hold);
    return true;
}

void release_hardware_rank(const QString &factory_name)
{
    QMutexLocker locker(&rank_hold_mutex);
    auto existing = rank_holds.find(factory_name);
    if (existing == rank_holds.end())
        return;
    if (--existing->holders > 0)
        return;
    GstPluginFeature *feature = gst_registry_find_feature(
        gst_registry_get(), factory_name.toUtf8().constData(), GST_TYPE_ELEMENT_FACTORY);
    if (feature) {
        gst_plugin_feature_set_rank(feature, existing->original_rank);
        gst_object_unref(feature);
    }
    rank_holds.erase(existing);
}

std::optional<bool> buffer_appears_black(GstBuffer *buffer, GstCaps *caps)
{
    GstVideoInfo video_info;
    if (!caps || !gst_video_info_from_caps(&video_info, caps))
        return std::nullopt;
    const GstVideoFormatInfo *format = video_info.finfo;
    if (!format || GST_VIDEO_FORMAT_INFO_N_COMPONENTS(format) < 1)
        return std::nullopt;
    GstVideoFrame frame;
    if (!gst_video_frame_map(&frame, &video_info, buffer, GST_MAP_READ))
        return std::nullopt;
    const bool rgb = GST_VIDEO_FORMAT_INFO_IS_RGB(format);
    const int components = rgb ? std::min(3, static_cast<int>(
        GST_VIDEO_FORMAT_INFO_N_COMPONENTS(format))) : 1;
    bool black = true;
    for (int component = 0; component < components; ++component) {
        if (GST_VIDEO_FORMAT_INFO_DEPTH(format, component) > 8) {
            gst_video_frame_unmap(&frame);
            return std::nullopt;
        }
        const int width = GST_VIDEO_FRAME_COMP_WIDTH(&frame, component);
        const int height = GST_VIDEO_FRAME_COMP_HEIGHT(&frame, component);
        const int stride = GST_VIDEO_FRAME_COMP_STRIDE(&frame, component);
        const int pixel_stride = GST_VIDEO_FRAME_COMP_PSTRIDE(&frame, component);
        const guint8 *data = GST_VIDEO_FRAME_COMP_DATA(&frame, component);
        if (!data || width <= 0 || height <= 0 || stride <= 0 || pixel_stride <= 0) {
            gst_video_frame_unmap(&frame);
            return std::nullopt;
        }
        quint64 total = 0;
        int minimum = 255;
        int maximum = 0;
        int samples = 0;
        for (int y_index = 0; y_index < 8; ++y_index) {
            const int y = std::min(height - 1, y_index * height / 8 + height / 16);
            for (int x_index = 0; x_index < 8; ++x_index) {
                const int x = std::min(width - 1, x_index * width / 8 + width / 16);
                const int value = data[y * stride + x * pixel_stride];
                total += static_cast<quint64>(value);
                minimum = std::min(minimum, value);
                maximum = std::max(maximum, value);
                ++samples;
            }
        }
        const double mean = static_cast<double>(total) / static_cast<double>(samples);
        const double threshold = rgb ? 8.0 : 24.0;
        black = black && mean <= threshold && maximum - minimum <= 8;
    }
    gst_video_frame_unmap(&frame);
    return black;
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
#if defined(Q_OS_ANDROID)
    GST_PLUGIN_STATIC_REGISTER(qml6);
    GstElementFactory *qml_factory = gst_element_factory_find("qml6glsink");
    if (!qml_factory) {
        error = QStringLiteral("The audited static Android qml6 EGL plug-in could not register");
        return false;
    }
    gst_object_unref(qml_factory);
#endif
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
        // GStreamer 1.28.6 whepclientsrc currently emits an H.264 offer that
        // common WHEP servers such as MediaMTX reject.  The same locked Rust
        // source also ships whepsrc, whose explicit RTP caps are the upstream
        // documented compatibility path.  Prefer it while retaining the new
        // client as a fail-closed fallback for runtimes that omit webrtchttp.
        source_ = gst_element_factory_make("whepsrc", "directSource");
        decoder_bin_ = make("decodebin3", "directDecoder", error);
        if (!decoder_bin_)
            return false;
        if (source_) {
            const QByteArray video_encoding = endpoint_.video_codec.compare(
                QStringLiteral("h265"), Qt::CaseInsensitive) == 0 ? "H265" : "H264";
            const QByteArray video_description = QByteArray(
                "application/x-rtp,media=video,encoding-name=") + video_encoding +
                ",payload=127,clock-rate=90000";
            GstCaps *video_caps = gst_caps_from_string(video_description.constData());
            const QString audio_codec = endpoint_.audio_codec.toLower();
            QByteArray audio_description(
                "application/x-rtp,media=audio,encoding-name=PCMU,payload=0,clock-rate=8000");
            if (audio_codec == QStringLiteral("opus"))
                audio_description = "application/x-rtp,media=audio,encoding-name=OPUS,"
                                    "payload=111,clock-rate=48000,encoding-params=(string)2";
            else if (audio_codec == QStringLiteral("pcma") ||
                     audio_codec == QStringLiteral("alaw") ||
                     audio_codec == QStringLiteral("g711a"))
                audio_description = "application/x-rtp,media=audio,encoding-name=PCMA,"
                                    "payload=8,clock-rate=8000";
            GstCaps *audio_caps = gst_caps_from_string(audio_description.constData());
            if (!video_caps || !audio_caps) {
                if (video_caps)
                    gst_caps_unref(video_caps);
                if (audio_caps)
                    gst_caps_unref(audio_caps);
                error = QStringLiteral("WHEP RTP capability construction failed");
                return false;
            }
            g_object_set(source_, "whep-endpoint", endpoint_.endpoint.toUtf8().constData(),
                         "use-link-headers", TRUE, "timeout", 3u,
                         "video-caps", video_caps, "audio-caps", audio_caps, nullptr);
            gst_caps_unref(video_caps);
            gst_caps_unref(audio_caps);
            if (!endpoint_.bearer_token.isEmpty())
                g_object_set(source_, "auth-token",
                             endpoint_.bearer_token.toUtf8().constData(), nullptr);
        } else {
            source_ = make("whepclientsrc", "directSource", error);
            if (!source_)
                return false;
            GObject *signaller = nullptr;
            if (g_object_class_find_property(G_OBJECT_GET_CLASS(source_), "signaller"))
                g_object_get(source_, "signaller", &signaller, nullptr);
            if (!signaller || !g_object_class_find_property(
                    G_OBJECT_GET_CLASS(signaller), "whep-endpoint")) {
                if (signaller)
                    g_object_unref(signaller);
                error = QStringLiteral("WHEP runtime has no compatible client signaller");
                return false;
            }
            g_object_set(signaller, "whep-endpoint",
                         endpoint_.endpoint.toUtf8().constData(), nullptr);
            if (!endpoint_.bearer_token.isEmpty()) {
                if (!g_object_class_find_property(G_OBJECT_GET_CLASS(signaller), "auth-token")) {
                    g_object_unref(signaller);
                    error = QStringLiteral("WHEP runtime does not support bearer authentication");
                    return false;
                }
                g_object_set(signaller, "auth-token",
                             endpoint_.bearer_token.toUtf8().constData(), nullptr);
            }
            g_object_unref(signaller);
        }
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
    software_fallback_forced_ = false;
    fallback_reason_.clear();
    decoder_ = QStringLiteral("discovering");
    hardware_decode_ = false;
    frames_decoded_.store(0, std::memory_order_relaxed);
    frames_dropped_.store(0, std::memory_order_relaxed);
    visual_samples_.store(0, std::memory_order_relaxed);
    black_samples_.store(0, std::memory_order_relaxed);
    pipeline_restarts_.store(0, std::memory_order_relaxed);
    video_width_.store(0, std::memory_order_relaxed);
    video_height_.store(0, std::memory_order_relaxed);
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
    restore_failed_hardware_rank();
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
    if (self->software_fallback_forced_) {
        self->fallback_reason_ = QStringLiteral("hardware_decoder_failed_software_fallback");
        self->restore_failed_hardware_rank();
    } else {
        self->fallback_reason_ = self->hardware_decode_ ? QString{} :
            QStringLiteral("hardware_decoder_unavailable");
    }
    QMetaObject::invokeMethod(self, [self] { emit self->diagnosticsChanged(); }, Qt::QueuedConnection);
}

GstPadProbeReturn MediaPipeline::video_buffer_probe(GstPad *pad, GstPadProbeInfo *info,
                                                    gpointer context)
{
    auto *self = static_cast<MediaPipeline *>(context);
    if (!GST_PAD_PROBE_INFO_BUFFER(info))
        return GST_PAD_PROBE_OK;
    GstCaps *caps = gst_pad_get_current_caps(pad);
    if (caps && gst_caps_get_size(caps) > 0) {
        const GstStructure *structure = gst_caps_get_structure(caps, 0);
        int width = 0;
        int height = 0;
        if (gst_structure_get_int(structure, "width", &width) &&
            gst_structure_get_int(structure, "height", &height)) {
            self->video_width_.store(width, std::memory_order_relaxed);
            self->video_height_.store(height, std::memory_order_relaxed);
        }
    }
    const quint64 previous = self->frames_decoded_.fetch_add(1, std::memory_order_relaxed);
    // Evidence probes use a fakesink and may map sparse raw frames. Never force a
    // GPU-to-CPU readback on the interactive qml6glsink rendering path.
    if (!self->video_item_ && previous % 30 == 0) {
        const std::optional<bool> black = buffer_appears_black(
            GST_PAD_PROBE_INFO_BUFFER(info), caps);
        if (black.has_value()) {
            self->visual_samples_.fetch_add(1, std::memory_order_relaxed);
            if (*black)
                self->black_samples_.fetch_add(1, std::memory_order_relaxed);
        }
    }
    if (caps)
        gst_caps_unref(caps);
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
    bool restart_scheduled = false;
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
                if (hold_hardware_rank(decoder_factory_))
                    failed_hardware_factory_ = decoder_factory_;
                software_fallback_forced_ = true;
                fallback_reason_ = QStringLiteral("hardware_decoder_failed_software_fallback");
                set_state(QStringLiteral("software-fallback"));
                bus_timer_.stop();
                restart_scheduled = true;
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
        if (!pipeline_ || restart_scheduled)
            break;
    }
    gst_object_unref(bus);
    if (restart_scheduled) {
        QTimer::singleShot(0, this, &MediaPipeline::restart_with_software_fallback);
        return;
    }
    if (statistics_clock_.isValid() && statistics_clock_.elapsed() >= 1000) {
        const quint64 current = frames_decoded_.load(std::memory_order_relaxed);
        const qint64 elapsed = statistics_clock_.restart();
        current_fps_ = elapsed > 0 ? 1000.0 * static_cast<double>(current - last_reported_frames_) /
                                     static_cast<double>(elapsed) : 0.0;
        last_reported_frames_ = current;
        emit statisticsChanged();
    }
}

void MediaPipeline::restart_with_software_fallback()
{
    pipeline_restarts_.fetch_add(1, std::memory_order_relaxed);
    direct_timeout_.stop();
    bus_timer_.stop();
    if (pipeline_) {
        gst_element_set_state(pipeline_, GST_STATE_NULL);
        gst_object_unref(pipeline_);
    }
    pipeline_ = source_ = decoder_bin_ = video_convert_ = video_probe_ = video_sink_ = nullptr;
    audio_convert_ = audio_resample_ = audio_volume_ = audio_sink_ = nullptr;
    frames_decoded_.store(0, std::memory_order_relaxed);
    frames_dropped_.store(0, std::memory_order_relaxed);
    video_width_.store(0, std::memory_order_relaxed);
    video_height_.store(0, std::memory_order_relaxed);
    decoder_ = QStringLiteral("software-fallback-discovering");
    hardware_decode_ = false;
    current_fps_ = 0;

    QString error;
    if (!build_pipeline(error)) {
        restore_failed_hardware_rank();
        fail(error);
        return;
    }
    set_state(QStringLiteral("probing"));
    if (gst_element_set_state(pipeline_, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
        restore_failed_hardware_rank();
        fail(QStringLiteral("software fallback pipeline could not start"));
        return;
    }
    if (!statistics_clock_.isValid())
        statistics_clock_.start();
    else
        statistics_clock_.restart();
    last_reported_frames_ = 0;
    bus_timer_.start();
    direct_timeout_.start();
    emit diagnosticsChanged();
}

void MediaPipeline::restore_failed_hardware_rank()
{
    if (failed_hardware_factory_.isEmpty())
        return;
    release_hardware_rank(failed_hardware_factory_);
    failed_hardware_factory_.clear();
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
int MediaPipeline::videoWidth() const { return video_width_.load(std::memory_order_relaxed); }
int MediaPipeline::videoHeight() const { return video_height_.load(std::memory_order_relaxed); }
quint64 MediaPipeline::visualSamples() const { return visual_samples_.load(std::memory_order_relaxed); }
quint64 MediaPipeline::blackSamples() const { return black_samples_.load(std::memory_order_relaxed); }
quint64 MediaPipeline::pipelineRestarts() const { return pipeline_restarts_.load(std::memory_order_relaxed); }

}
