#include "webobs/client/client_controller.hpp"

#include <QDateTime>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QNetworkReply>
#include <QUrl>

#if defined(Q_OS_ANDROID)
#include <QJniObject>
#endif

namespace webobs::client {

ClientController::ClientController(QObject *parent) : QObject(parent)
{
    QString error;
    bool restored_active_grant = false;
    const QByteArray stored = secure_store_.load(error);
    if (!stored.isEmpty()) {
        identity_ = DeviceIdentity::deserialize(stored, error);
        if (identity_.valid()) {
            server_url_ = identity_.control_server_url;
            if (!identity_.latest_grant_bundle.isEmpty()) {
                QJsonParseError parse_error;
                const QJsonDocument document = QJsonDocument::fromJson(
                    identity_.latest_grant_bundle, &parse_error);
                if (parse_error.error == QJsonParseError::NoError && document.isObject())
                    grant_ = GrantCodec::open_bundle(document.object(), identity_, error);
                else
                    error = QStringLiteral("stored sealed grant is invalid");
            }
            if (error.isEmpty() && !identity_.latest_shared_scenes.isEmpty()) {
                QJsonParseError scene_error;
                const QJsonDocument scenes = QJsonDocument::fromJson(
                    identity_.latest_shared_scenes, &scene_error);
                if (scene_error.error != QJsonParseError::NoError || !scenes.isArray() ||
                    (!scenes.array().isEmpty() && !scene_.load(scenes.array().first().toObject())))
                    error = QStringLiteral("stored shared Scene cache is invalid");
            }
            if (error.isEmpty() && grant_.expires_at > QDateTime::currentSecsSinceEpoch()) {
                set_state(QStringLiteral("offline-ready"),
                          QStringLiteral("Encrypted offline authorization loaded"));
                restored_active_grant = true;
            } else if (error.isEmpty()) {
                set_state(QStringLiteral("grant-expired"),
                          QStringLiteral("Stored authorization expired; reconnect to renew"));
            }
        }
    }
    if (!error.isEmpty())
        emit userError(error);
    enrollment_poll_.setInterval(1000);
    connect(&enrollment_poll_, &QTimer::timeout, this, &ClientController::pollEnrollment);
    online_validation_.setInterval(10'000);
    connect(&online_validation_, &QTimer::timeout, this, [this] { bootstrap_internal(true); });
    grant_expiry_.setInterval(1000);
    connect(&grant_expiry_, &QTimer::timeout, this, [this] {
        if (grant_.expires_at > 0 && QDateTime::currentSecsSinceEpoch() >= grant_.expires_at) {
            grant_expiry_.stop();
            online_validation_.stop();
            stopAll();
            set_state(QStringLiteral("grant-expired"), QStringLiteral("Offline authorization expired"));
            emit userError(QStringLiteral("This device must reconnect and renew its 30-day grant"));
        }
    });
    if (restored_active_grant)
        grant_expiry_.start();
    if (restored_active_grant && !server_url_.isEmpty())
        online_validation_.start();
    connect(&media_, &MediaPipeline::directReady, this, [this] {
        submit_media_plan(QStringLiteral("reachable"));
    });
    connect(&media_, &MediaPipeline::directFailed, this, [this](const QString &reason) {
        fallback_reason_ = reason;
        emit topologyChanged();
        submit_media_plan(QStringLiteral("unreachable"));
    });
    connect(qGuiApp, &QGuiApplication::applicationStateChanged, this, [this](Qt::ApplicationState state) {
        if (state != Qt::ApplicationActive) {
            stopAll();
            setMonitoringFullscreen(false);
        }
    });
}

QString ClientController::platform()
{
#if defined(Q_OS_ANDROID)
    return QStringLiteral("android");
#elif defined(Q_OS_WIN)
    return QStringLiteral("windows");
#else
    return QStringLiteral("linux");
#endif
}

QStringList ClientController::hardware_decoders()
{
#if defined(Q_OS_ANDROID)
    return {QStringLiteral("mediacodec")};
#elif defined(Q_OS_WIN)
    return {QStringLiteral("d3d11")};
#else
    return {QStringLiteral("vaapi")};
#endif
}

void ClientController::request(const QByteArray &method, const QString &path, const QJsonObject *body,
                               bool device_authenticated, ReplyHandler handler,
                               bool quiet_network_errors)
{
    const QUrl base(server_url_);
    if (!base.isValid() || (base.scheme() != QStringLiteral("https") &&
        !(base.scheme() == QStringLiteral("http") &&
          (base.host() == QStringLiteral("127.0.0.1") || base.host() == QStringLiteral("localhost"))))) {
        emit userError(QStringLiteral("Server URL must use HTTPS; HTTP is allowed only on loopback"));
        return;
    }
    QNetworkRequest request(base.resolved(QUrl(path)));
    request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    request.setRawHeader("Accept", "application/json");
    request.setRawHeader("User-Agent", "WebObs-Native/2.0");
    if (device_authenticated) {
        if (identity_.device_token.isEmpty()) {
            emit userError(QStringLiteral("Device identity is unavailable"));
            return;
        }
        request.setRawHeader("Authorization", "WebObs-Device " + identity_.device_token.toLatin1());
    }
    const QByteArray payload = body ? QJsonDocument(*body).toJson(QJsonDocument::Compact) : QByteArray{};
    QNetworkReply *reply = network_.sendCustomRequest(request, method, payload);
    connect(reply, &QNetworkReply::finished, this,
            [this, reply, handler = std::move(handler), quiet_network_errors] {
        const QByteArray data = reply->readAll();
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        QJsonParseError parser_error;
        const QJsonDocument document = QJsonDocument::fromJson(data, &parser_error);
        QJsonObject object = document.isObject() ? document.object() : QJsonObject{};
        if (reply->error() != QNetworkReply::NoError && status == 0) {
            if (!quiet_network_errors)
                emit userError(QStringLiteral("Control server is unreachable"));
        } else if (parser_error.error != QJsonParseError::NoError || data.size() > 1024 * 1024) {
            if (!quiet_network_errors)
                emit userError(QStringLiteral("Control server returned invalid bounded JSON"));
        } else {
            handler(status, object);
        }
        reply->deleteLater();
    });
}

void ClientController::enroll(const QString &name)
{
    QString error;
    identity_ = GrantCodec::create_identity(error);
    identity_.control_server_url = server_url_;
    QJsonObject body = GrantCodec::enrollment_request(name, platform(), identity_, error);
    if (!error.isEmpty()) {
        emit userError(error);
        return;
    }
    set_state(QStringLiteral("enrolling"), QStringLiteral("Requesting a ten-minute pairing code"));
    request("POST", QStringLiteral("/api/v2/enrollments"), &body, false,
            [this](int status, const QJsonObject &response) {
        if (status != 201) {
            emit userError(QStringLiteral("Enrollment request was rejected"));
            set_state(QStringLiteral("unpaired"), QStringLiteral("Enrollment failed"));
            return;
        }
        enrollment_id_ = response.value("enrollmentId").toString();
        pairing_code_ = response.value("pairingCode").toString();
        identity_.device_token = response.value("deviceToken").toString();
        if (enrollment_id_.size() != 32 || pairing_code_.size() != 8 ||
            identity_.device_token.size() < 32) {
            emit userError(QStringLiteral("Enrollment response is invalid"));
            return;
        }
        persist_identity();
        set_state(QStringLiteral("pending-approval"), QStringLiteral("Approve this code in WebObs Admin"));
        emit enrollmentChanged();
        enrollment_poll_.start();
    });
}

void ClientController::pollEnrollment()
{
    if (enrollment_id_.isEmpty())
        return;
    request("POST", QStringLiteral("/api/v2/enrollments/%1/complete").arg(enrollment_id_),
            nullptr, true, [this](int status, const QJsonObject &response) {
        if (status == 202)
            return;
        if (status != 200) {
            enrollment_poll_.stop();
            emit userError(QStringLiteral("Enrollment completion was rejected or expired"));
            return;
        }
        QString error;
        grant_ = GrantCodec::open_bundle(response.value("grantBundle").toObject(), identity_, error);
        if (!error.isEmpty()) {
            enrollment_poll_.stop();
            emit userError(error);
            return;
        }
        enrollment_poll_.stop();
        persist_identity();
        grant_expiry_.start();
        online_validation_.start();
        set_state(QStringLiteral("ready"), QStringLiteral("Paired; True Direct is available"));
        emit bootstrapChanged();
        bootstrap();
    });
}

void ClientController::bootstrap()
{
    bootstrap_internal(false);
}

void ClientController::bootstrap_internal(bool quiet_network_errors)
{
    if (!identity_.valid())
        return;
    request("GET", QStringLiteral("/api/v2/client/bootstrap?sinceRevision=%1")
                       .arg(identity_.bootstrap_revision),
            nullptr, true, [this](int status, const QJsonObject &response) {
        if (status == 401) {
            stopAll();
            online_validation_.stop();
            set_state(QStringLiteral("revoked"), QStringLiteral("Device was revoked or its grant expired"));
            return;
        }
        if (status != 200)
            return;
        QString error;
        GrantDocument renewed = GrantCodec::open_bundle(response.value("grantBundle").toObject(),
                                                         identity_, error);
        if (!error.isEmpty()) {
            emit userError(error);
            return;
        }
        const qint64 next_revision = response.value("revision").toInteger(-1);
        if (next_revision < identity_.bootstrap_revision) {
            emit userError(QStringLiteral("Control server bootstrap revision moved backwards"));
            return;
        }
        const QJsonArray shared_scenes = response.value("sharedScenes").toArray();
        if (response.value("changed").toBool()) {
            if (!shared_scenes.isEmpty() && !scene_.load(shared_scenes.first().toObject())) {
                emit userError(QStringLiteral("Control server returned an invalid shared Scene"));
                return;
            }
            identity_.latest_shared_scenes = QJsonDocument(shared_scenes).toJson(
                QJsonDocument::Compact);
        }
        grant_ = std::move(renewed);
        identity_.bootstrap_revision = next_revision;
        persist_identity();
        emit bootstrapChanged();
    }, quiet_network_errors);
}

QVariantMap ClientController::camera(const QString &camera_id) const
{
    for (const QVariant &value : grant_.cameras) {
        const QVariantMap camera = value.toMap();
        if (camera.value("cameraId").toString() == camera_id)
            return camera;
    }
    return {};
}

QVariantMap ClientController::profile(const QVariantMap &camera, const QString &profile_id) const
{
    for (const QVariant &value : camera.value("profiles").toList()) {
        const QVariantMap profile = value.toMap();
        if (profile.value("id").toString() == profile_id)
            return profile;
    }
    return {};
}

void ClientController::startCamera(const QString &camera_id, const QString &profile_id,
                                   const QString &policy)
{
    if (grant_.expires_at <= QDateTime::currentSecsSinceEpoch()) {
        stopAll();
        emit userError(QStringLiteral("Offline authorization expired; reconnect before playback"));
        return;
    }
    const QVariantMap selected_camera = camera(camera_id);
    const QVariantMap selected_profile = profile(selected_camera, profile_id);
    if (selected_camera.isEmpty() || selected_profile.isEmpty()) {
        emit userError(QStringLiteral("Camera/Profile is outside this device grant"));
        return;
    }
    const QVariantMap credentials = selected_camera.value("credentials").toMap();
    QString selected_adapter = selected_profile.value("adapter").toString();
    if (selected_adapter.isEmpty())
        selected_adapter = selected_camera.value("adapter").toString();
    MediaEndpoint endpoint;
    endpoint.adapter = selected_adapter;
    endpoint.endpoint = selected_profile.value("endpoint").toString();
    endpoint.video_codec = selected_profile.value("videoCodec").toString();
    endpoint.username = credentials.value("username").toString();
    endpoint.password = credentials.value("password").toString();
    current_camera_id_ = camera_id;
    current_profile_id_ = profile_id;
    current_policy_ = policy;
    live_topology_ = QStringLiteral("probing-true-direct");
    archive_topology_ = QStringLiteral("unknown");
    fallback_reason_.clear();
    emit topologyChanged();
    QString error;
    if (!media_.start(endpoint, error)) {
        fallback_reason_ = error;
        emit topologyChanged();
        submit_media_plan(QStringLiteral("unreachable"));
    }
}

void ClientController::submit_media_plan(const QString &reachability)
{
    const QVariantMap selected_camera = camera(current_camera_id_);
    const QVariantMap selected_profile = profile(selected_camera, current_profile_id_);
    QString selected_adapter = selected_profile.value("adapter").toString();
    if (selected_adapter.isEmpty())
        selected_adapter = selected_camera.value("adapter").toString();
    QJsonObject body{{"cameraId", current_camera_id_}, {"profileId", current_profile_id_},
        {"policy", current_policy_}, {"receiverKind", "native"}, {"networkClass", "lan"},
        {"reachability", reachability},
        {"protocols", QJsonArray{selected_adapter}},
        {"videoCodecs", QJsonArray{selected_profile.value("videoCodec").toString()}},
        {"hardwareDecoders", QJsonArray::fromStringList(hardware_decoders())},
        {"requiresComposite", false}};
    request("POST", QStringLiteral("/api/v2/media-plans"), &body, true,
            [this](int status, const QJsonObject &response) {
        QString error;
        const TopologyPlan plan = TopologyPlan::from_json(response, error);
        if (!error.isEmpty()) {
            emit userError(error);
            return;
        }
        live_topology_ = plan.topology;
        archive_topology_ = plan.archive_topology;
        fallback_reason_ = plan.fallback_reason;
        emit topologyChanged();
        if (status == 409 || !plan.true_direct()) {
            media_.stop();
            if (current_policy_ == QStringLiteral("true-direct-only"))
                emit userError(QStringLiteral("True Direct Only blocked fallback: %1").arg(plan.fallback_reason));
            else
                emit userError(QStringLiteral("Fallback required: %1").arg(plan.fallback_reason));
        }
    });
}

void ClientController::attachVideoItem(QObject *item) { media_.set_video_item(item); }
void ClientController::stopAll() { media_.stop(); live_topology_ = QStringLiteral("off"); emit topologyChanged(); }

void ClientController::revokeLocalIdentity()
{
    stopAll();
    QString error;
    if (!secure_store_.clear(error))
        emit userError(error);
    identity_ = {};
    grant_ = {};
    set_state(QStringLiteral("unpaired"), QStringLiteral("Local identity removed"));
    emit enrollmentChanged();
    emit bootstrapChanged();
}

bool ClientController::startManualRecording(const QString &path)
{
    QString error;
    const bool started = media_.start_recording(path, error);
    if (!started)
        emit userError(error);
    return started;
}

void ClientController::setMonitoringFullscreen(bool active)
{
#if defined(Q_OS_ANDROID)
    QJniObject::callStaticMethod<void>("org/webobs/nativeclient/KeyStoreBridge", "setWakeLock",
                                       "(Z)V", static_cast<jboolean>(active));
#else
    Q_UNUSED(active)
#endif
}

void ClientController::persist_identity()
{
    QString warning;
    if (!secure_store_.save(identity_.serialize(), warning))
        emit userError(warning);
    else if (!warning.isEmpty())
        emit userError(warning);
}

void ClientController::set_state(const QString &value, const QString &status)
{
    state_ = value;
    status_text_ = status;
    emit stateChanged();
}

QString ClientController::serverUrl() const { return server_url_; }
void ClientController::setServerUrl(const QString &value)
{
    const QString normalized = value.trimmed();
    if (server_url_ != normalized) {
        server_url_ = normalized;
        if (identity_.valid()) {
            identity_.control_server_url = server_url_;
            persist_identity();
        }
        emit serverUrlChanged();
    }
}
QString ClientController::state() const { return state_; }
QString ClientController::pairingCode() const { return pairing_code_; }
QString ClientController::statusText() const { return status_text_; }
QString ClientController::storageBackend() const { return secure_store_.backend(); }
bool ClientController::temporaryIdentity() const { return !secure_store_.persistent_available(); }
QVariantList ClientController::cameras() const { return grant_.cameras; }
QString ClientController::liveTopology() const { return live_topology_; }
QString ClientController::archiveTopology() const { return archive_topology_; }
QString ClientController::fallbackReason() const { return fallback_reason_; }
MediaPipeline *ClientController::media() { return &media_; }
SceneModel *ClientController::scene() { return &scene_; }

}
