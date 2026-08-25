#pragma once

#include "webobs/client/media_pipeline.hpp"

#include <QAbstractListModel>
#include <QPointer>

#include <memory>
#include <optional>
#include <vector>

namespace webobs::client {

struct StreamPlanContext {
    QString session_id;
    QString camera_id;
    QString profile_id;
    QString policy;
    QString adapter;
    QString video_codec;
    QString endpoint;
};

class StreamSessionModel final : public QAbstractListModel {
    Q_OBJECT
    Q_PROPERTY(int count READ count NOTIFY countChanged)
    Q_PROPERTY(int capacity READ capacity CONSTANT)

public:
    enum Role {
        SessionIdRole = Qt::UserRole + 1,
        CameraIdRole,
        ProfileIdRole,
        TitleRole,
        MediaRole,
        TopologyRole,
        ArchiveTopologyRole,
        FallbackReasonRole,
        FocusedRole,
        ReconnectCountRole,
    };

    explicit StreamSessionModel(int capacity, bool focused, QObject *parent = nullptr,
                                bool allowDuplicates = false);
    ~StreamSessionModel() override;

    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;
    int count() const;
    int capacity() const;

    QString prepare(const QString &camera_id, const QString &profile_id, const QString &title,
                    const QString &policy, const MediaEndpoint &endpoint, QString &error);
    Q_INVOKABLE void attach(const QString &session_id, QObject *video_item);
    Q_INVOKABLE void remove(const QString &session_id);
    Q_INVOKABLE void setMuted(const QString &session_id, bool muted);
    Q_INVOKABLE bool startRecording(const QString &session_id, const QString &absolute_mkv_path);
    Q_INVOKABLE void stopRecording(const QString &session_id);
    void clear();
    void halt(const QString &session_id);
    void suspend();
    void resume();
    std::optional<StreamPlanContext> context(const QString &session_id) const;
    void set_plan(const QString &session_id, const QString &topology,
                  const QString &archive_topology, const QString &fallback_reason);
    bool activate_fallback(const QString &session_id, const QString &plan_id,
                           qint64 expires_at, const MediaEndpoint &endpoint, QString &error);
    static int reconnectDelayMs(int reconnectCount);

signals:
    void countChanged();
    void directResult(const QString &sessionId, bool reachable, const QString &reason);
    void fallbackReleaseRequested(const QString &planId);
    void userError(const QString &message);

private:
    struct Session {
        QString id;
        QString camera_id;
        QString profile_id;
        QString title;
        QString policy;
        QString topology = QStringLiteral("probing-true-direct");
        QString archive_topology = QStringLiteral("unknown");
        QString fallback_reason;
        MediaEndpoint direct_endpoint;
        MediaEndpoint endpoint;
        std::unique_ptr<MediaPipeline> pipeline;
        QPointer<QObject> video_item;
        bool ever_ready = false;
        bool server_fallback = false;
        bool retry_pending = false;
        int reconnect_count = 0;
        QString plan_id;
        qint64 fallback_expires_at = 0;
    };

    int find(const QString &session_id) const;
    void start(int row);
    void restore_expired_fallback(int row);
    void schedule_reconnect(const QString &session_id, const QString &reason);
    void notify_row(int row);

    int capacity_;
    bool focused_;
    bool allow_duplicates_;
    bool suspended_ = false;
    std::vector<std::unique_ptr<Session>> sessions_;
};

}
