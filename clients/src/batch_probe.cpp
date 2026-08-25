#include "webobs/client/batch_probe.hpp"

#include "webobs/client/media_pipeline.hpp"

#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QElapsedTimer>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSet>
#include <QTextStream>
#include <QTimer>
#include <QUrl>

#include <algorithm>
#include <memory>
#include <vector>

namespace webobs::client {
namespace {

struct ProbeEntry {
    QString name;
    MediaEndpoint endpoint;
};

struct BatchState {
    std::vector<ProbeEntry> entries;
    std::vector<std::unique_ptr<MediaPipeline>> pipelines;
    std::vector<bool> ever_ready;
    std::vector<bool> retry_pending;
    std::vector<bool> recovering;
    std::vector<int> retry_attempts;
    std::vector<int> reconnects;
    std::vector<quint64> decoded_before_retry;
    std::vector<quint64> dropped_before_retry;
    int duration_seconds = 0;
    int ready = 0;
    int result = 4;
    bool finished = false;
    bool reconnect_on_failure = false;
    bool resume_after_background = false;
    bool background_released = false;
    bool resuming = false;
    int resumed = 0;
};

bool parse_manifest(const QString &path, BatchState &state, QString &error)
{
    const QFileInfo info(path);
    if (!info.isAbsolute() || !info.isFile() || info.size() <= 0 || info.size() > 1024 * 1024) {
        error = QStringLiteral("batch probe manifest must be an absolute bounded file");
        return false;
    }
    QFile file(info.absoluteFilePath());
    if (!file.open(QIODevice::ReadOnly)) {
        error = QStringLiteral("batch probe manifest could not be opened");
        return false;
    }
    QJsonParseError parse_error;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parse_error);
    if (parse_error.error != QJsonParseError::NoError || !document.isObject()) {
        error = QStringLiteral("batch probe manifest is invalid JSON");
        return false;
    }
    const QJsonObject root = document.object();
    const QJsonArray streams = root.value(QStringLiteral("streams")).toArray();
    const int duration = root.value(QStringLiteral("durationSeconds")).toInt();
    if (root.value(QStringLiteral("schemaVersion")).toInt() != 1 || duration < 1 ||
        duration > 7200 || streams.isEmpty() || streams.size() > 32) {
        error = QStringLiteral("batch probe manifest has invalid bounded fields");
        return false;
    }
    const QSet<QString> adapters{QStringLiteral("rtsp"), QStringLiteral("mjpeg"),
                                 QStringLiteral("hls"), QStringLiteral("whep")};
    const QSet<QString> codecs{QStringLiteral("h264"), QStringLiteral("h265"),
                               QStringLiteral("mjpeg")};
    const QRegularExpression safe_name(QStringLiteral("^[A-Za-z0-9._-]{1,64}$"));
    const QRegularExpression safe_environment(QStringLiteral("^WEBOBS_PRIVATE_[A-Z0-9_]{1,80}$"));
    QSet<QString> names;
    for (const QJsonValue &value : streams) {
        if (!value.isObject()) {
            error = QStringLiteral("batch probe stream is invalid");
            return false;
        }
        const QJsonObject item = value.toObject();
        ProbeEntry entry;
        entry.name = item.value(QStringLiteral("name")).toString();
        entry.endpoint.adapter = item.value(QStringLiteral("adapter")).toString().toLower();
        entry.endpoint.endpoint = item.value(QStringLiteral("endpoint")).toString();
        entry.endpoint.video_codec = item.value(QStringLiteral("codec")).toString().toLower();
        const QString username_environment = item.value(QStringLiteral("usernameEnv")).toString();
        const QString password_environment = item.value(QStringLiteral("passwordEnv")).toString();
        const QUrl endpoint(entry.endpoint.endpoint);
        if (!safe_name.match(entry.name).hasMatch() || names.contains(entry.name) ||
            !adapters.contains(entry.endpoint.adapter) ||
            !codecs.contains(entry.endpoint.video_codec) || !endpoint.isValid() ||
            endpoint.host().isEmpty() || !endpoint.userInfo().isEmpty() ||
            entry.endpoint.endpoint.size() > 2048 ||
            (!username_environment.isEmpty() &&
             !safe_environment.match(username_environment).hasMatch()) ||
            (!password_environment.isEmpty() &&
             !safe_environment.match(password_environment).hasMatch())) {
            error = QStringLiteral("batch probe stream fields are invalid");
            return false;
        }
        names.insert(entry.name);
        entry.endpoint.username = qEnvironmentVariable(username_environment.toUtf8().constData());
        entry.endpoint.password = qEnvironmentVariable(password_environment.toUtf8().constData());
        state.entries.push_back(std::move(entry));
    }
    state.duration_seconds = duration;
    return true;
}

void finish_batch(QGuiApplication &application, BatchState &state)
{
    if (state.finished)
        return;
    state.finished = true;
    QJsonArray streams;
    bool valid = true;
    for (std::size_t index = 0; index < state.pipelines.size(); ++index) {
        MediaPipeline &pipeline = *state.pipelines[index];
        const quint64 decoded = state.decoded_before_retry[index] + pipeline.framesDecoded();
        const quint64 dropped = state.dropped_before_retry[index] + pipeline.framesDropped();
        streams.append(QJsonObject{{QStringLiteral("name"), state.entries[index].name},
            {QStringLiteral("decoder"), pipeline.decoder().left(128)},
            {QStringLiteral("hardwareDecode"), pipeline.hardwareDecode()},
            {QStringLiteral("fallbackReason"), pipeline.fallbackReason().left(128)},
            {QStringLiteral("framesDecoded"), static_cast<qint64>(decoded)},
            {QStringLiteral("framesDropped"), static_cast<qint64>(dropped)},
            {QStringLiteral("fps"), pipeline.currentFps()},
            {QStringLiteral("width"), pipeline.videoWidth()},
            {QStringLiteral("height"), pipeline.videoHeight()},
            {QStringLiteral("visualSamples"), static_cast<qint64>(pipeline.visualSamples())},
            {QStringLiteral("blackSamples"), static_cast<qint64>(pipeline.blackSamples())},
            {QStringLiteral("pipelineRestarts"), static_cast<qint64>(pipeline.pipelineRestarts())},
            {QStringLiteral("networkReconnects"), state.reconnects[index]}});
        valid = valid && decoded >= static_cast<quint64>(state.duration_seconds);
        pipeline.stop();
    }
    if (valid) {
        QTextStream output(stdout);
        output << QJsonDocument(QJsonObject{{QStringLiteral("result"), QStringLiteral("passed")},
            {QStringLiteral("processCount"), 1}, {QStringLiteral("streams"), streams}})
                      .toJson(QJsonDocument::Compact)
               << Qt::endl;
        state.result = 0;
    }
    application.quit();
}

void schedule_retry(QGuiApplication &application, BatchState &state, std::size_t index)
{
    if (state.finished || index >= state.pipelines.size() || state.retry_pending[index])
        return;
    state.retry_pending[index] = true;
    const int exponent = std::min(state.retry_attempts[index], 2);
    const int delay_ms = 1000 * (1 << exponent);
    ++state.retry_attempts[index];
    QTimer::singleShot(delay_ms, &application, [&application, &state, index] {
        if (state.finished || index >= state.pipelines.size())
            return;
        state.retry_pending[index] = false;
        QString start_error;
        if (!state.pipelines[index]->start(state.entries[index].endpoint, start_error))
            schedule_retry(application, state, index);
    });
}

void release_background_batch(QGuiApplication &application, BatchState &state)
{
    if (state.finished || state.background_released ||
        state.ready != static_cast<int>(state.pipelines.size()))
        return;
    state.background_released = true;
    QElapsedTimer elapsed;
    elapsed.start();
    for (const auto &pipeline : state.pipelines)
        pipeline->stop();
    QTextStream output(stdout);
    output << QJsonDocument(QJsonObject{
        {QStringLiteral("result"), QStringLiteral("background-released")},
        {QStringLiteral("streamCount"), static_cast<int>(state.pipelines.size())},
        {QStringLiteral("releaseMilliseconds"), elapsed.elapsed()}})
                  .toJson(QJsonDocument::Compact)
           << Qt::endl;
    const qint64 release_milliseconds = elapsed.elapsed();
    if (release_milliseconds > 5000 || !state.resume_after_background) {
        state.finished = true;
        state.result = release_milliseconds <= 5000 ? 0 : 4;
        application.quit();
    }
}

}

int run_batch_probe(QGuiApplication &application, const QString &manifest_path, QString &error,
                    bool release_on_background, bool reconnect_on_failure,
                    bool resume_after_background)
{
    BatchState state;
    if (!parse_manifest(manifest_path, state, error))
        return 2;
    state.pipelines.reserve(state.entries.size());
    state.ever_ready.assign(state.entries.size(), false);
    state.retry_pending.assign(state.entries.size(), false);
    state.recovering.assign(state.entries.size(), false);
    state.retry_attempts.assign(state.entries.size(), 0);
    state.reconnects.assign(state.entries.size(), 0);
    state.decoded_before_retry.assign(state.entries.size(), 0);
    state.dropped_before_retry.assign(state.entries.size(), 0);
    state.reconnect_on_failure = reconnect_on_failure;
    state.resume_after_background = resume_after_background;
    for (std::size_t index = 0; index < state.entries.size(); ++index) {
        auto pipeline = std::make_unique<MediaPipeline>();
        QObject::connect(pipeline.get(), &MediaPipeline::directReady, &application,
            [&application, &state, release_on_background, index] {
                if (state.resuming && state.ever_ready[index]) {
                    ++state.resumed;
                    if (state.resumed == static_cast<int>(state.pipelines.size())) {
                        state.resuming = false;
                        state.finished = true;
                        state.result = 0;
                        QTextStream output(stdout);
                        output << QJsonDocument(QJsonObject{
                            {QStringLiteral("result"), QStringLiteral("foreground-resumed")},
                            {QStringLiteral("streamCount"), state.resumed}})
                                      .toJson(QJsonDocument::Compact)
                               << Qt::endl;
                        for (const auto &entry : state.pipelines)
                            entry->stop();
                        application.quit();
                    }
                    return;
                }
                if (state.ever_ready[index] && state.recovering[index]) {
                    state.recovering[index] = false;
                    state.retry_attempts[index] = 0;
                    ++state.reconnects[index];
                    QTextStream output(stdout);
                    output << QJsonDocument(QJsonObject{
                        {QStringLiteral("result"), QStringLiteral("reconnected")},
                        {QStringLiteral("name"), state.entries[index].name},
                        {QStringLiteral("networkReconnects"), state.reconnects[index]}})
                                  .toJson(QJsonDocument::Compact)
                           << Qt::endl;
                    return;
                }
                state.ever_ready[index] = true;
                ++state.ready;
                if (state.ready == static_cast<int>(state.pipelines.size())) {
                    QTextStream output(stdout);
                    output << QJsonDocument(QJsonObject{
                        {QStringLiteral("result"), QStringLiteral("ready")},
                        {QStringLiteral("streamCount"), state.ready}})
                                  .toJson(QJsonDocument::Compact)
                           << Qt::endl;
                    if (!release_on_background)
                        QTimer::singleShot(state.duration_seconds * 1000, &application,
                            [&application, &state] { finish_batch(application, state); });
                }
            });
        QObject::connect(pipeline.get(), &MediaPipeline::directFailed, &application,
            [&application, &state, index](const QString &) {
                if (state.finished)
                    return;
                if (state.reconnect_on_failure && state.ever_ready[index]) {
                    state.decoded_before_retry[index] += state.pipelines[index]->framesDecoded();
                    state.dropped_before_retry[index] += state.pipelines[index]->framesDropped();
                    state.recovering[index] = true;
                    state.pipelines[index]->stop();
                    schedule_retry(application, state, index);
                } else {
                    state.finished = true;
                    state.result = 4;
                    application.quit();
                }
            });
        state.pipelines.push_back(std::move(pipeline));
    }
    if (release_on_background) {
        QObject::connect(&application, &QGuiApplication::applicationStateChanged, &application,
            [&application, &state](Qt::ApplicationState application_state) {
                if (application_state != Qt::ApplicationActive) {
                    release_background_batch(application, state);
                    return;
                }
                if (!state.resume_after_background || !state.background_released ||
                    state.resuming || state.finished)
                    return;
                state.resuming = true;
                state.resumed = 0;
                for (std::size_t index = 0; index < state.pipelines.size(); ++index) {
                    QString start_error;
                    if (!state.pipelines[index]->start(state.entries[index].endpoint,
                                                       start_error)) {
                        state.finished = true;
                        state.result = 4;
                        application.quit();
                        return;
                    }
                }
            });
    }
    for (std::size_t index = 0; index < state.pipelines.size(); ++index) {
        QString start_error;
        if (!state.pipelines[index]->start(state.entries[index].endpoint, start_error)) {
            error = QStringLiteral("batch probe stream could not start");
            return 4;
        }
    }
    QTimer::singleShot((state.duration_seconds + 15) * 1000, &application,
        [&application, &state] {
            if (!state.finished) {
                state.finished = true;
                state.result = 4;
                application.quit();
            }
        });
    application.exec();
    return state.result;
}

}
