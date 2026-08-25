#pragma once

#include "webobs/client/grant_codec.hpp"
#include "webobs/client/scene_model.hpp"
#include "webobs/client/secure_store.hpp"
#include "webobs/client/stream_session_model.hpp"
#include "webobs/client/studio_workspace.hpp"
#include "webobs/client/talk_capture.hpp"
#include "webobs/client/topology_plan.hpp"

#include <QNetworkAccessManager>
#include <QHash>
#include <QObject>
#include <QTimer>

#include <functional>

namespace webobs::client {

class ClientController final : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString serverUrl READ serverUrl WRITE setServerUrl NOTIFY serverUrlChanged)
    Q_PROPERTY(QString state READ state NOTIFY stateChanged)
    Q_PROPERTY(QString pairingCode READ pairingCode NOTIFY enrollmentChanged)
    Q_PROPERTY(QString statusText READ statusText NOTIFY stateChanged)
    Q_PROPERTY(QString storageBackend READ storageBackend CONSTANT)
    Q_PROPERTY(bool temporaryIdentity READ temporaryIdentity NOTIFY enrollmentChanged)
    Q_PROPERTY(QVariantList cameras READ cameras NOTIFY bootstrapChanged)
    Q_PROPERTY(QString liveTopology READ liveTopology NOTIFY topologyChanged)
    Q_PROPERTY(QString archiveTopology READ archiveTopology NOTIFY topologyChanged)
    Q_PROPERTY(QString fallbackReason READ fallbackReason NOTIFY topologyChanged)
    Q_PROPERTY(StreamSessionModel* gridStreams READ gridStreams CONSTANT)
    Q_PROPERTY(StreamSessionModel* focusStreams READ focusStreams CONSTANT)
    Q_PROPERTY(StreamSessionModel* studioPreviewStreams READ studioPreviewStreams CONSTANT)
    Q_PROPERTY(StreamSessionModel* studioProgramStreams READ studioProgramStreams CONSTANT)
    Q_PROPERTY(int gridCapacity READ gridCapacity NOTIFY gridChanged)
    Q_PROPERTY(SceneModel* scene READ scene CONSTANT)
    Q_PROPERTY(StudioWorkspace* studio READ studio CONSTANT)
    Q_PROPERTY(bool talkActive READ talkActive NOTIFY talkActiveChanged)
    Q_PROPERTY(bool androidPlatform READ androidPlatform CONSTANT)
    Q_PROPERTY(int hardwareDecoderInstances READ hardwareDecoderInstances NOTIFY platformStatusChanged)
    Q_PROPERTY(bool grid16Available READ grid16Available NOTIFY platformStatusChanged)
    Q_PROPERTY(bool wakeLockActive READ wakeLockActive NOTIFY platformStatusChanged)
    Q_PROPERTY(QString networkStatus READ networkStatus NOTIFY platformStatusChanged)
    Q_PROPERTY(QString thermalStatus READ thermalStatus NOTIFY platformStatusChanged)
    Q_PROPERTY(QString lastCapturePath READ lastCapturePath NOTIFY lastCapturePathChanged)

public:
    explicit ClientController(QObject *parent = nullptr);
    QString serverUrl() const;
    void setServerUrl(const QString &value);
    QString state() const;
    QString pairingCode() const;
    QString statusText() const;
    QString storageBackend() const;
    bool temporaryIdentity() const;
    QVariantList cameras() const;
    QString liveTopology() const;
    QString archiveTopology() const;
    QString fallbackReason() const;
    StreamSessionModel *gridStreams();
    StreamSessionModel *focusStreams();
    StreamSessionModel *studioPreviewStreams();
    StreamSessionModel *studioProgramStreams();
    int gridCapacity() const;
    SceneModel *scene();
    StudioWorkspace *studio();
    bool talkActive() const;
    bool androidPlatform() const;
    int hardwareDecoderInstances() const;
    bool grid16Available() const;
    bool wakeLockActive() const;
    QString networkStatus() const;
    QString thermalStatus() const;
    QString lastCapturePath() const;

    Q_INVOKABLE void enroll(const QString &name);
    Q_INVOKABLE void pollEnrollment();
    Q_INVOKABLE void bootstrap();
    Q_INVOKABLE void startCamera(const QString &cameraId, const QString &profileId,
                                 const QString &policy = QStringLiteral("auto"));
    Q_INVOKABLE void activateGrid(int capacity);
    Q_INVOKABLE void focusCamera(const QString &cameraId);
    Q_INVOKABLE void closeFocus();
    Q_INVOKABLE void attachStream(bool focused, const QString &sessionId, QObject *videoItem);
    Q_INVOKABLE void removeStream(bool focused, const QString &sessionId);
    Q_INVOKABLE QString startStudioCamera(bool program, const QString &cameraId,
                                          const QString &profileId);
    Q_INVOKABLE void attachStudioStream(bool program, const QString &sessionId, QObject *videoItem);
    Q_INVOKABLE void removeStudioStream(bool program, const QString &sessionId);
    Q_INVOKABLE void setStudioActive(bool active);
    Q_INVOKABLE void stopAll();
    Q_INVOKABLE void revokeLocalIdentity();
    Q_INVOKABLE bool startManualRecording(bool focused, const QString &sessionId,
                                          const QString &absoluteMkvPath);
    Q_INVOKABLE void stopManualRecording(bool focused, const QString &sessionId);
    Q_INVOKABLE void setListening(bool focused, const QString &sessionId, bool enabled);
    Q_INVOKABLE bool cameraHasPermission(const QString &cameraId, const QString &permission) const;
    Q_INVOKABLE void movePtz(const QString &cameraId, qreal x, qreal y, qreal zoom = 0);
    Q_INVOKABLE void stopPtz(const QString &cameraId);
    Q_INVOKABLE void saveSnapshot(const QString &cameraId, const QString &absolutePath);
    Q_INVOKABLE void saveLocalScreenshot(const QString &cameraId, QObject *visualItem,
                                         const QString &absolutePath);
    Q_INVOKABLE QString suggestedCapturePath(const QString &extension) const;
    Q_INVOKABLE void startTalk(const QString &cameraId);
    Q_INVOKABLE void finishTalk();
    Q_INVOKABLE void cancelTalk();
    Q_INVOKABLE void exportMkvToMp4(const QString &absoluteMkvPath,
                                    const QString &absoluteMp4Path);
    Q_INVOKABLE void setMonitoringFullscreen(bool active);
    Q_INVOKABLE void exportLastCapture();

signals:
    void serverUrlChanged();
    void stateChanged();
    void enrollmentChanged();
    void bootstrapChanged();
    void topologyChanged();
    void gridChanged();
    void userError(const QString &message);
    void operationCompleted(const QString &message);
    void talkActiveChanged();
    void platformStatusChanged();
    void lastCapturePathChanged();

private:
    using ReplyHandler = std::function<void(int, const QJsonObject &)>;
    void request(const QByteArray &method, const QString &path, const QJsonObject *body,
                 bool device_authenticated, ReplyHandler handler, bool quiet_network_errors = false);
    void bootstrap_internal(bool quiet_network_errors);
    void persist_identity();
    void set_state(const QString &value, const QString &status);
    void submit_media_plan(StreamSessionModel *model, const QString &session_id,
                           const QString &reachability);
    void release_media_plan(const QString &plan_id);
    void camera_operation(const QString &camera_id, const QString &operation,
                          const QJsonObject *body, ReplyHandler handler);
    QVariantMap camera(const QString &camera_id) const;
    QVariantMap profile(const QVariantMap &camera, const QString &profile_id) const;
    QVariantMap profile_for_role(const QVariantMap &camera, const QString &role) const;
    MediaEndpoint media_endpoint(const QVariantMap &camera, const QVariantMap &profile) const;
    QString prepare_stream(StreamSessionModel &model, const QVariantMap &camera,
                           const QVariantMap &profile, const QString &policy);
    static QString platform();
    static QStringList hardware_decoders();
    void refresh_platform_status();
    void set_last_capture_path(const QString &path);
    void finalize_pending_recordings();

    QNetworkAccessManager network_;
    SecureStore secure_store_;
    DeviceIdentity identity_;
    GrantDocument grant_;
    StreamSessionModel grid_streams_{16, false};
    StreamSessionModel focus_streams_{1, true};
    StreamSessionModel studio_preview_streams_{64, false, nullptr, true};
    StreamSessionModel studio_program_streams_{64, false, nullptr, true};
    StudioWorkspace studio_;
    TalkCapture talk_capture_;
    QTimer enrollment_poll_;
    QTimer online_validation_;
    QTimer grant_expiry_;
    QTimer platform_status_poll_;
    QString server_url_;
    QString enrollment_id_;
    QString pairing_code_;
    QString state_ = QStringLiteral("unpaired");
    QString status_text_ = QStringLiteral("Not paired");
    int grid_capacity_ = 4;
    QString live_topology_ = QStringLiteral("off");
    QString archive_topology_ = QStringLiteral("off");
    QString fallback_reason_;
    QString talk_camera_id_;
    int hardware_decoder_instances_ = 0;
    bool wake_lock_active_ = false;
    QString network_status_ = QStringLiteral("unknown");
    QString thermal_status_ = QStringLiteral("unknown");
    QString last_capture_path_;
    QHash<QString, QString> pending_recordings_;
};

}
