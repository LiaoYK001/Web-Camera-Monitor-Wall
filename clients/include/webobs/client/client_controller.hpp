#pragma once

#include "webobs/client/grant_codec.hpp"
#include "webobs/client/media_pipeline.hpp"
#include "webobs/client/scene_model.hpp"
#include "webobs/client/secure_store.hpp"
#include "webobs/client/topology_plan.hpp"

#include <QNetworkAccessManager>
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
    Q_PROPERTY(MediaPipeline* media READ media CONSTANT)
    Q_PROPERTY(SceneModel* scene READ scene CONSTANT)

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
    MediaPipeline *media();
    SceneModel *scene();

    Q_INVOKABLE void enroll(const QString &name);
    Q_INVOKABLE void pollEnrollment();
    Q_INVOKABLE void bootstrap();
    Q_INVOKABLE void attachVideoItem(QObject *item);
    Q_INVOKABLE void startCamera(const QString &cameraId, const QString &profileId,
                                 const QString &policy = QStringLiteral("auto"));
    Q_INVOKABLE void stopAll();
    Q_INVOKABLE void revokeLocalIdentity();
    Q_INVOKABLE bool startManualRecording(const QString &absoluteMkvPath);
    Q_INVOKABLE void setMonitoringFullscreen(bool active);

signals:
    void serverUrlChanged();
    void stateChanged();
    void enrollmentChanged();
    void bootstrapChanged();
    void topologyChanged();
    void userError(const QString &message);

private:
    using ReplyHandler = std::function<void(int, const QJsonObject &)>;
    void request(const QByteArray &method, const QString &path, const QJsonObject *body,
                 bool device_authenticated, ReplyHandler handler, bool quiet_network_errors = false);
    void bootstrap_internal(bool quiet_network_errors);
    void persist_identity();
    void set_state(const QString &value, const QString &status);
    void submit_media_plan(const QString &reachability);
    QVariantMap camera(const QString &camera_id) const;
    QVariantMap profile(const QVariantMap &camera, const QString &profile_id) const;
    static QString platform();
    static QStringList hardware_decoders();

    QNetworkAccessManager network_;
    SecureStore secure_store_;
    DeviceIdentity identity_;
    GrantDocument grant_;
    MediaPipeline media_;
    SceneModel scene_;
    QTimer enrollment_poll_;
    QTimer online_validation_;
    QTimer grant_expiry_;
    QString server_url_;
    QString enrollment_id_;
    QString pairing_code_;
    QString state_ = QStringLiteral("unpaired");
    QString status_text_ = QStringLiteral("Not paired");
    QString current_camera_id_;
    QString current_profile_id_;
    QString current_policy_ = QStringLiteral("auto");
    QString live_topology_ = QStringLiteral("off");
    QString archive_topology_ = QStringLiteral("off");
    QString fallback_reason_;
};

}
