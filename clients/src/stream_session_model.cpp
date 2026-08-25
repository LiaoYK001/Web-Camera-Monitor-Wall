#include "webobs/client/stream_session_model.hpp"

#include <QDateTime>
#include <QTimer>
#include <QUuid>

#include <algorithm>

namespace webobs::client {

StreamSessionModel::StreamSessionModel(int capacity, bool focused, QObject *parent,
                                       bool allow_duplicates)
    : QAbstractListModel(parent), capacity_(capacity), focused_(focused),
      allow_duplicates_(allow_duplicates)
{
}

StreamSessionModel::~StreamSessionModel() = default;

int StreamSessionModel::rowCount(const QModelIndex &parent) const
{
    return parent.isValid() ? 0 : static_cast<int>(sessions_.size());
}

QVariant StreamSessionModel::data(const QModelIndex &index, int role) const
{
    if (!index.isValid() || index.row() < 0 || index.row() >= rowCount())
        return {};
    const Session &session = *sessions_[static_cast<std::size_t>(index.row())];
    switch (role) {
    case SessionIdRole: return session.id;
    case CameraIdRole: return session.camera_id;
    case ProfileIdRole: return session.profile_id;
    case TitleRole: return session.title;
    case MediaRole: return QVariant::fromValue(static_cast<QObject *>(session.pipeline.get()));
    case TopologyRole: return session.topology;
    case ArchiveTopologyRole: return session.archive_topology;
    case FallbackReasonRole: return session.fallback_reason;
    case FocusedRole: return focused_;
    case ReconnectCountRole: return session.reconnect_count;
    default: return {};
    }
}

QHash<int, QByteArray> StreamSessionModel::roleNames() const
{
    return {{SessionIdRole, "sessionId"}, {CameraIdRole, "cameraId"},
            {ProfileIdRole, "profileId"}, {TitleRole, "title"}, {MediaRole, "media"},
            {TopologyRole, "topology"}, {ArchiveTopologyRole, "archiveTopology"},
            {FallbackReasonRole, "fallbackReason"}, {FocusedRole, "focused"},
            {ReconnectCountRole, "reconnectCount"}};
}

int StreamSessionModel::count() const { return rowCount(); }
int StreamSessionModel::capacity() const { return capacity_; }

QString StreamSessionModel::prepare(const QString &camera_id, const QString &profile_id,
                                    const QString &title, const QString &policy,
                                    const MediaEndpoint &endpoint, QString &error)
{
    if (camera_id.isEmpty() || profile_id.isEmpty() || endpoint.endpoint.isEmpty()) {
        error = QStringLiteral("stream session requires a granted Camera/Profile endpoint");
        return {};
    }
    if (focused_ && !sessions_.empty())
        clear();
    if (static_cast<int>(sessions_.size()) >= capacity_) {
        error = QStringLiteral("stream grid reached its bounded capacity");
        return {};
    }
    if (!focused_ && !allow_duplicates_) {
        const auto duplicate = std::find_if(sessions_.begin(), sessions_.end(),
            [&camera_id](const auto &session) { return session->camera_id == camera_id; });
        if (duplicate != sessions_.end())
            return (*duplicate)->id;
    }

    auto session = std::make_unique<Session>();
    session->id = QUuid::createUuid().toString(QUuid::WithoutBraces);
    session->camera_id = camera_id;
    session->profile_id = profile_id;
    session->title = title.left(128);
    session->policy = policy;
    session->direct_endpoint = endpoint;
    session->endpoint = endpoint;
    session->pipeline = std::make_unique<MediaPipeline>();
    const QString id = session->id;
    connect(session->pipeline.get(), &MediaPipeline::directReady, this, [this, id] {
        const int row = find(id);
        if (row < 0)
            return;
        Session &current = *sessions_[static_cast<std::size_t>(row)];
        current.ever_ready = true;
        current.retry_pending = false;
        if (!current.server_fallback)
            current.fallback_reason.clear();
        notify_row(row);
        if (!current.server_fallback)
            emit directResult(id, true, {});
    });
    connect(session->pipeline.get(), &MediaPipeline::directFailed, this,
            [this, id](const QString &reason) {
        const int row = find(id);
        if (row < 0)
            return;
        Session &current = *sessions_[static_cast<std::size_t>(row)];
        current.fallback_reason = reason.left(256);
        notify_row(row);
        if (current.server_fallback || current.ever_ready ||
            reason == QStringLiteral("hardware_decoder_failed_software_fallback"))
            schedule_reconnect(id, reason);
        else
            emit directResult(id, false, reason);
    });
    connect(session->pipeline.get(), &MediaPipeline::diagnosticsChanged, this, [this, id] {
        const int row = find(id);
        if (row >= 0)
            notify_row(row);
    });

    const int row = rowCount();
    beginInsertRows({}, row, row);
    sessions_.push_back(std::move(session));
    endInsertRows();
    emit countChanged();
    return id;
}

void StreamSessionModel::attach(const QString &session_id, QObject *video_item)
{
    const int row = find(session_id);
    if (row < 0 || !video_item)
        return;
    Session &session = *sessions_[static_cast<std::size_t>(row)];
    session.video_item = video_item;
    session.pipeline->setVideoItem(video_item);
    if (!suspended_ && session.pipeline->state() == QStringLiteral("idle"))
        start(row);
}

void StreamSessionModel::remove(const QString &session_id)
{
    const int row = find(session_id);
    if (row < 0)
        return;
    const QString plan_id = sessions_[static_cast<std::size_t>(row)]->plan_id;
    beginRemoveRows({}, row, row);
    sessions_.erase(sessions_.begin() + row);
    endRemoveRows();
    emit countChanged();
    if (!plan_id.isEmpty())
        emit fallbackReleaseRequested(plan_id);
}

void StreamSessionModel::setMuted(const QString &session_id, bool muted)
{
    const int row = find(session_id);
    if (row >= 0)
        sessions_[static_cast<std::size_t>(row)]->pipeline->set_muted(muted);
}

bool StreamSessionModel::startRecording(const QString &session_id, const QString &absolute_mkv_path)
{
    const int row = find(session_id);
    if (row < 0)
        return false;
    QString error;
    if (!sessions_[static_cast<std::size_t>(row)]->pipeline->start_recording(absolute_mkv_path, error)) {
        emit userError(error);
        return false;
    }
    notify_row(row);
    return true;
}

void StreamSessionModel::stopRecording(const QString &session_id)
{
    const int row = find(session_id);
    if (row >= 0) {
        sessions_[static_cast<std::size_t>(row)]->pipeline->stopRecording();
        notify_row(row);
    }
}

void StreamSessionModel::clear()
{
    if (sessions_.empty())
        return;
    QStringList plans;
    for (const auto &session : sessions_)
        if (!session->plan_id.isEmpty() && !plans.contains(session->plan_id))
            plans.push_back(session->plan_id);
    beginResetModel();
    sessions_.clear();
    endResetModel();
    emit countChanged();
    for (const QString &plan : plans)
        emit fallbackReleaseRequested(plan);
}

void StreamSessionModel::halt(const QString &session_id)
{
    const int row = find(session_id);
    if (row >= 0) {
        sessions_[static_cast<std::size_t>(row)]->retry_pending = false;
        sessions_[static_cast<std::size_t>(row)]->pipeline->stop();
        notify_row(row);
    }
}

void StreamSessionModel::suspend()
{
    suspended_ = true;
    for (auto &session : sessions_) {
        session->retry_pending = false;
        session->pipeline->stop();
    }
}

void StreamSessionModel::resume()
{
    if (!suspended_)
        return;
    suspended_ = false;
    for (int row = 0; row < rowCount(); ++row)
        start(row);
}

std::optional<StreamPlanContext> StreamSessionModel::context(const QString &session_id) const
{
    const int row = find(session_id);
    if (row < 0)
        return std::nullopt;
    const Session &session = *sessions_[static_cast<std::size_t>(row)];
    return StreamPlanContext{session.id, session.camera_id, session.profile_id, session.policy,
                             session.endpoint.adapter, session.endpoint.video_codec,
                             session.endpoint.endpoint};
}

void StreamSessionModel::set_plan(const QString &session_id, const QString &topology,
                                  const QString &archive_topology, const QString &fallback_reason)
{
    const int row = find(session_id);
    if (row < 0)
        return;
    Session &session = *sessions_[static_cast<std::size_t>(row)];
    session.topology = topology;
    session.archive_topology = archive_topology;
    session.fallback_reason = fallback_reason.left(256);
    notify_row(row);
}

bool StreamSessionModel::activate_fallback(const QString &session_id, const QString &plan_id,
                                           qint64 expires_at, const MediaEndpoint &endpoint,
                                           QString &error)
{
    const int row = find(session_id);
    if (row < 0 || plan_id.size() != 32 || endpoint.adapter != QStringLiteral("whep") ||
        endpoint.endpoint.isEmpty() || endpoint.bearer_token.isEmpty() ||
        expires_at <= QDateTime::currentSecsSinceEpoch()) {
        error = QStringLiteral("server fallback activation contract is invalid");
        return false;
    }
    Session &session = *sessions_[static_cast<std::size_t>(row)];
    session.pipeline->stop();
    session.endpoint = endpoint;
    session.plan_id = plan_id;
    session.fallback_expires_at = expires_at;
    session.server_fallback = true;
    session.ever_ready = false;
    session.retry_pending = false;
    session.reconnect_count = 0;
    notify_row(row);
    if (!suspended_ && session.video_item)
        start(row);
    return true;
}

int StreamSessionModel::find(const QString &session_id) const
{
    for (int row = 0; row < rowCount(); ++row) {
        if (sessions_[static_cast<std::size_t>(row)]->id == session_id)
            return row;
    }
    return -1;
}

void StreamSessionModel::start(int row)
{
    if (suspended_ || row < 0 || row >= rowCount())
        return;
    restore_expired_fallback(row);
    Session &session = *sessions_[static_cast<std::size_t>(row)];
    if (!session.video_item)
        return;
    session.pipeline->setVideoItem(session.video_item.data());
    QString error;
    if (!session.pipeline->start(session.endpoint, error)) {
        session.fallback_reason = error.left(256);
        notify_row(row);
        if (session.ever_ready)
            schedule_reconnect(session.id, error);
        else
            emit directResult(session.id, false, error);
    }
}

void StreamSessionModel::restore_expired_fallback(int row)
{
    if (row < 0 || row >= rowCount())
        return;
    Session &session = *sessions_[static_cast<std::size_t>(row)];
    if (!session.server_fallback || session.fallback_expires_at == 0 ||
        QDateTime::currentSecsSinceEpoch() < session.fallback_expires_at)
        return;

    const QString expired_plan = session.plan_id;
    session.pipeline->stop();
    session.endpoint = session.direct_endpoint;
    session.plan_id.clear();
    session.fallback_expires_at = 0;
    session.server_fallback = false;
    session.ever_ready = false;
    session.retry_pending = false;
    session.reconnect_count = 0;
    session.topology = QStringLiteral("probing-true-direct");
    session.fallback_reason = QStringLiteral("server_fallback_plan_expired_reprobe");
    notify_row(row);
    if (!expired_plan.isEmpty())
        emit fallbackReleaseRequested(expired_plan);
}

void StreamSessionModel::schedule_reconnect(const QString &session_id, const QString &reason)
{
    const int row = find(session_id);
    if (row < 0 || suspended_)
        return;
    Session &session = *sessions_[static_cast<std::size_t>(row)];
    if (session.retry_pending)
        return;
    session.retry_pending = true;
    session.topology = QStringLiteral("reconnecting-true-direct");
    session.fallback_reason = reason.left(256);
    const int delay_ms = reconnectDelayMs(session.reconnect_count);
    ++session.reconnect_count;
    notify_row(row);
    QTimer::singleShot(delay_ms, this, [this, session_id] {
        const int current_row = find(session_id);
        if (current_row < 0 || suspended_)
            return;
        sessions_[static_cast<std::size_t>(current_row)]->retry_pending = false;
        start(current_row);
    });
}

int StreamSessionModel::reconnectDelayMs(int reconnect_count)
{
    const int exponent = std::clamp(reconnect_count, 0, 2);
    return 1000 * (1 << exponent);
}

void StreamSessionModel::notify_row(int row)
{
    if (row >= 0 && row < rowCount())
        emit dataChanged(index(row), index(row));
}

}
