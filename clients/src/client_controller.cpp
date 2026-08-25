#include "webobs/client/client_controller.hpp"
#include "webobs/client/application_lifecycle.hpp"
#include "webobs/client/network_policy.hpp"

#include <QDateTime>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QNetworkReply>
#include <QRegularExpression>
#include <QProcess>
#include <QQuickItem>
#include <QQuickItemGrabResult>
#include <QSaveFile>
#include <QStandardPaths>
#include <QUrl>

#include <sodium.h>

#include <limits>
#include <algorithm>
#include <memory>
#include <utility>

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
                    (!scenes.array().isEmpty() && !studio_.load(scenes.array())))
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
    // Keep enough headroom for the authenticated bootstrap round-trip so an
    // online revocation stops media inside the public ten-second contract.
    online_validation_.setInterval(5'000);
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
    platform_status_poll_.setInterval(1000);
    connect(&platform_status_poll_, &QTimer::timeout,
            this, &ClientController::refresh_platform_status);
    refresh_platform_status();
    platform_status_poll_.start();
    const auto wire_streams = [this](StreamSessionModel &model) {
        StreamSessionModel *stream_model = &model;
        connect(&model, &StreamSessionModel::directResult, this,
            [this, stream_model](const QString &session_id, bool reachable, const QString &reason) {
                if (!reachable) {
                    fallback_reason_ = reason;
                    emit topologyChanged();
                }
                submit_media_plan(stream_model, session_id,
                                  reachable ? QStringLiteral("reachable") :
                                              QStringLiteral("unreachable"));
            });
        connect(&model, &StreamSessionModel::userError, this, &ClientController::userError);
        connect(&model, &StreamSessionModel::fallbackReleaseRequested,
                this, &ClientController::release_media_plan);
    };
    wire_streams(grid_streams_);
    wire_streams(focus_streams_);
    wire_streams(studio_preview_streams_);
    wire_streams(studio_program_streams_);
    connect(qGuiApp, &QGuiApplication::applicationStateChanged, this, [this](Qt::ApplicationState state) {
#if defined(Q_OS_ANDROID)
        constexpr bool mobile = true;
#else
        constexpr bool mobile = false;
#endif
        if (should_suspend_for_application_state(state, mobile)) {
            cancelTalk();
            finalize_pending_recordings();
            grid_streams_.suspend();
            focus_streams_.suspend();
            studio_preview_streams_.suspend();
            studio_program_streams_.suspend();
            setMonitoringFullscreen(false);
        } else if (grant_.expires_at > QDateTime::currentSecsSinceEpoch()) {
            grid_streams_.resume();
            focus_streams_.resume();
            studio_preview_streams_.resume();
            studio_program_streams_.resume();
        }
    });
    connect(&talk_capture_, &TalkCapture::activeChanged, this, &ClientController::talkActiveChanged);
    connect(&talk_capture_, &TalkCapture::failed, this, &ClientController::userError);
    connect(&talk_capture_, &TalkCapture::captured, this, [this](const QByteArray &wav) {
        if (talk_camera_id_.isEmpty())
            return;
        QJsonObject body{{QStringLiteral("operation"), QStringLiteral("start")},
            {QStringLiteral("contentType"), QStringLiteral("audio/wav")},
            {QStringLiteral("data"), QString::fromLatin1(wav.toBase64())}};
        const QString camera_id = std::exchange(talk_camera_id_, {});
        camera_operation(camera_id, QStringLiteral("talk"), &body,
            [this](int status, const QJsonObject &) {
                if (status != 200) {
                    emit userError(QStringLiteral("Push-to-Talk audio was rejected"));
                    return;
                }
                emit operationCompleted(QStringLiteral("Push-to-Talk audio accepted (maximum 10 seconds)"));
            });
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
    constexpr qsizetype maximum_response_bytes = 1024 * 1024;
    auto response = std::make_shared<QByteArray>();
    auto oversized = std::make_shared<bool>(false);
    connect(reply, &QNetworkReply::readyRead, this,
            [reply, response, oversized] {
        if (*oversized)
            return;
        response->append(reply->read(maximum_response_bytes + 1 - response->size()));
        if (response->size() > maximum_response_bytes || reply->bytesAvailable() > 0) {
            *oversized = true;
            reply->abort();
        }
    });
    connect(reply, &QNetworkReply::finished, this,
            [this, reply, response, oversized, handler = std::move(handler), quiet_network_errors] {
        if (!*oversized)
            response->append(reply->read(maximum_response_bytes + 1 - response->size()));
        if (response->size() > maximum_response_bytes)
            *oversized = true;
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        QJsonParseError parser_error;
        const QJsonDocument document = QJsonDocument::fromJson(*response, &parser_error);
        QJsonObject object = document.isObject() ? document.object() : QJsonObject{};
        if (*oversized) {
            if (!quiet_network_errors)
                emit userError(QStringLiteral("Control server returned invalid bounded JSON"));
        } else if (reply->error() != QNetworkReply::NoError && status == 0) {
            if (!quiet_network_errors)
                emit userError(QStringLiteral("Control server is unreachable"));
        } else if (parser_error.error != QJsonParseError::NoError) {
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
        const int validation_seconds = response.value(
            QStringLiteral("onlineValidationIntervalSeconds")).toInt(0);
        if (validation_seconds < 1 || validation_seconds > 5) {
            emit userError(QStringLiteral(
                "Control server returned an unsafe online validation interval"));
            return;
        }
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
            if (!shared_scenes.isEmpty() && !studio_.load(shared_scenes)) {
                emit userError(QStringLiteral("Control server returned an invalid shared Scene"));
                return;
            }
            identity_.latest_shared_scenes = QJsonDocument(shared_scenes).toJson(
                QJsonDocument::Compact);
        }
        grant_ = std::move(renewed);
        online_validation_.setInterval(validation_seconds * 1000);
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

QVariantMap ClientController::profile_for_role(const QVariantMap &camera, const QString &role) const
{
    QVariantMap fallback;
    qint64 fallback_pixels = role == QStringLiteral("main") ? -1 : std::numeric_limits<qint64>::max();
    for (const QVariant &value : camera.value("profiles").toList()) {
        const QVariantMap candidate = value.toMap();
        if (candidate.value("role").toString() == role)
            return candidate;
        const qint64 pixels = candidate.value("width").toLongLong() *
                              candidate.value("height").toLongLong();
        if (fallback.isEmpty() || (role == QStringLiteral("main") ? pixels > fallback_pixels :
                                                                    pixels < fallback_pixels)) {
            fallback = candidate;
            fallback_pixels = pixels;
        }
    }
    return fallback;
}

MediaEndpoint ClientController::media_endpoint(const QVariantMap &selected_camera,
                                               const QVariantMap &selected_profile) const
{
    const QVariantMap credentials = selected_camera.value("credentials").toMap();
    MediaEndpoint endpoint;
    endpoint.adapter = selected_profile.value("adapter").toString();
    if (endpoint.adapter.isEmpty())
        endpoint.adapter = selected_camera.value("adapter").toString();
    endpoint.endpoint = selected_profile.value("endpoint").toString();
    endpoint.video_codec = selected_profile.value("videoCodec").toString().toLower();
    endpoint.audio_codec = selected_profile.value("audioCodec").toString().toLower();
    endpoint.username = credentials.value("username").toString();
    endpoint.password = credentials.value("password").toString();
    return endpoint;
}

QString ClientController::prepare_stream(StreamSessionModel &model, const QVariantMap &selected_camera,
                                         const QVariantMap &selected_profile, const QString &policy)
{
    if (selected_camera.isEmpty() || selected_profile.isEmpty()) {
        emit userError(QStringLiteral("Camera/Profile is outside this device grant"));
        return {};
    }
    QString error;
    const QString session_id = model.prepare(
        selected_camera.value("cameraId").toString(), selected_profile.value("id").toString(),
        selected_camera.value("name").toString(), policy,
        media_endpoint(selected_camera, selected_profile), error);
    if (!error.isEmpty())
        emit userError(error);
    return session_id;
}

void ClientController::startCamera(const QString &camera_id, const QString &profile_id,
                                   const QString &policy)
{
    if (grant_.expires_at <= QDateTime::currentSecsSinceEpoch()) {
        stopAll();
        emit userError(QStringLiteral("Offline authorization expired; reconnect before playback"));
        return;
    }
    focus_streams_.clear();
    live_topology_ = QStringLiteral("probing-true-direct");
    archive_topology_ = QStringLiteral("unknown");
    fallback_reason_.clear();
    emit topologyChanged();
    prepare_stream(focus_streams_, camera(camera_id), profile(camera(camera_id), profile_id), policy);
}

void ClientController::activateGrid(int capacity)
{
    if (!QList<int>{1, 4, 9, 16}.contains(capacity)) {
        emit userError(QStringLiteral("Grid capacity must be 1, 4, 9, or 16"));
        return;
    }
    if (capacity == 16 && !grid16Available()) {
        emit userError(QStringLiteral(
            "16-view requires at least 16 hardware MediaCodec decoder instances and a non-severe thermal state"));
        return;
    }
    if (grant_.expires_at <= QDateTime::currentSecsSinceEpoch()) {
        emit userError(QStringLiteral("Offline authorization expired; reconnect before playback"));
        return;
    }
    grid_streams_.clear();
    grid_capacity_ = capacity;
    int opened = 0;
    for (const QVariant &value : grant_.cameras) {
        if (opened >= capacity)
            break;
        const QVariantMap selected_camera = value.toMap();
        const QVariantMap selected_profile = profile_for_role(selected_camera, QStringLiteral("sub"));
        if (!selected_profile.isEmpty() &&
            !prepare_stream(grid_streams_, selected_camera, selected_profile, QStringLiteral("auto")).isEmpty())
            ++opened;
    }
    emit gridChanged();
}

void ClientController::focusCamera(const QString &camera_id)
{
    const QVariantMap selected_camera = camera(camera_id);
    prepare_stream(focus_streams_, selected_camera,
                   profile_for_role(selected_camera, QStringLiteral("main")), QStringLiteral("auto"));
}

void ClientController::closeFocus() { focus_streams_.clear(); }

void ClientController::attachStream(bool focused, const QString &session_id, QObject *video_item)
{
    (focused ? focus_streams_ : grid_streams_).attach(session_id, video_item);
}

void ClientController::removeStream(bool focused, const QString &session_id)
{
    (focused ? focus_streams_ : grid_streams_).remove(session_id);
}

QString ClientController::startStudioCamera(bool program, const QString &camera_id,
                                            const QString &profile_id)
{
    if (grant_.expires_at <= QDateTime::currentSecsSinceEpoch()) {
        emit userError(QStringLiteral("Offline authorization expired; reconnect before playback"));
        return {};
    }
    const QVariantMap selected_camera = camera(camera_id);
    return prepare_stream(program ? studio_program_streams_ : studio_preview_streams_,
                          selected_camera, profile(selected_camera, profile_id),
                          QStringLiteral("true-direct-only"));
}

void ClientController::attachStudioStream(bool program, const QString &session_id, QObject *video_item)
{
    (program ? studio_program_streams_ : studio_preview_streams_).attach(session_id, video_item);
}

void ClientController::removeStudioStream(bool program, const QString &session_id)
{
    (program ? studio_program_streams_ : studio_preview_streams_).remove(session_id);
}

void ClientController::setStudioActive(bool active)
{
    if (active) {
        grid_streams_.suspend();
        focus_streams_.suspend();
        studio_preview_streams_.resume();
        studio_program_streams_.resume();
    } else {
        studio_preview_streams_.suspend();
        studio_program_streams_.suspend();
        grid_streams_.resume();
        focus_streams_.resume();
    }
}

void ClientController::submit_media_plan(StreamSessionModel *model, const QString &session_id,
                                         const QString &reachability)
{
    if (!model)
        return;
    const std::optional<StreamPlanContext> selected = model->context(session_id);
    if (!selected)
        return;
    if (state_ == QStringLiteral("offline-ready")) {
        if (reachability == QStringLiteral("reachable") &&
            (selected->policy == QStringLiteral("true-direct-only") ||
             selected->policy == QStringLiteral("auto"))) {
            live_topology_ = QStringLiteral("true-direct");
            archive_topology_ = QStringLiteral("off");
            fallback_reason_.clear();
            model->set_plan(session_id, live_topology_, archive_topology_, {});
            emit topologyChanged();
        } else {
            model->halt(session_id);
            emit userError(QStringLiteral("Offline mode cannot negotiate a server fallback"));
        }
        return;
    }
    QJsonObject body{{"cameraId", selected->camera_id}, {"profileId", selected->profile_id},
        {"policy", selected->policy}, {"receiverKind", "native"},
        {"networkClass", classify_network(selected->endpoint)},
        {"reachability", reachability},
        {"protocols", QJsonArray{selected->adapter}},
        {"videoCodecs", QJsonArray{selected->video_codec}},
        {"hardwareDecoders", QJsonArray::fromStringList(hardware_decoders())},
        {"requiresComposite", false}};
    request("POST", QStringLiteral("/api/v2/media-plans"), &body, true,
            [this, model, session_id, policy = selected->policy,
             requested_camera = selected->camera_id,
             requested_profile = selected->profile_id](int status, const QJsonObject &response) {
        if (!model->context(session_id))
            return;
        QString error;
        const TopologyPlan plan = TopologyPlan::from_json(response, error);
        const bool status_matches = (status == 201 && plan.status == QStringLiteral("active")) ||
                                    (status == 409 && plan.status == QStringLiteral("rejected"));
        if (!error.isEmpty() || plan.camera_id != requested_camera ||
            plan.profile_id != requested_profile ||
            plan.receiver_kind != QStringLiteral("native") || !status_matches ||
            plan.expires_at <= QDateTime::currentSecsSinceEpoch()) {
            emit userError(QStringLiteral("TopologyPlan response did not match the media request"));
            return;
        }
        live_topology_ = plan.topology;
        archive_topology_ = plan.archive_topology;
        fallback_reason_ = plan.fallback_reason;
        model->set_plan(session_id, plan.topology, plan.archive_topology, plan.fallback_reason);
        emit topologyChanged();
        if (status == 409 || !plan.true_direct()) {
            model->halt(session_id);
            if (policy == QStringLiteral("true-direct-only")) {
                emit userError(QStringLiteral("True Direct Only blocked fallback: %1").arg(plan.fallback_reason));
                return;
            }
            emit userError(QStringLiteral("Activating %1 fallback: %2")
                               .arg(plan.topology, plan.fallback_reason));
            QJsonObject activation_request;
            request("POST", QStringLiteral("/api/v2/media-plans/%1/activate").arg(plan.plan_id),
                    &activation_request, true,
                    [this, model, session_id, plan](int activation_status,
                                                    const QJsonObject &activation) {
                if (activation_status != 200) {
                    emit userError(QStringLiteral("Server fallback activation failed safely"));
                    return;
                }
                const QJsonObject endpoint_value = activation.value("mediaEndpoint").toObject();
                if (activation.value("planId").toString() != plan.plan_id ||
                    endpoint_value.value("adapter").toString() != QStringLiteral("whep") ||
                    endpoint_value.value("authorization").toString() !=
                        QStringLiteral("device-bearer")) {
                    emit userError(QStringLiteral("Server fallback endpoint contract is invalid"));
                    release_media_plan(plan.plan_id);
                    return;
                }
                const QString relative = endpoint_value.value("endpoint").toString();
                const QString expected = QStringLiteral("/api/v2/media-plans/%1/whep")
                                             .arg(plan.plan_id);
                const QUrl server(server_url_);
                const QUrl resolved = server.resolved(QUrl(relative));
                if (relative != expected || !resolved.isValid() ||
                    resolved.scheme() != server.scheme() || resolved.host() != server.host() ||
                    resolved.port() != server.port() || !resolved.userInfo().isEmpty()) {
                    emit userError(QStringLiteral("Server fallback endpoint was rejected"));
                    release_media_plan(plan.plan_id);
                    return;
                }
                MediaEndpoint endpoint;
                endpoint.adapter = QStringLiteral("whep");
                endpoint.endpoint = resolved.toString(QUrl::FullyEncoded);
                endpoint.video_codec = QStringLiteral("h264");
                endpoint.audio_codec = QStringLiteral("opus");
                endpoint.bearer_token = identity_.device_token;
                QString error;
                if (!model->activate_fallback(session_id, plan.plan_id, plan.expires_at,
                                              endpoint, error)) {
                    release_media_plan(plan.plan_id);
                    if (!error.isEmpty())
                        emit userError(error);
                }
            });
        }
    });
}

void ClientController::release_media_plan(const QString &plan_id)
{
    static const QRegularExpression identifier(QStringLiteral("^[0-9a-f]{32}$"));
    if (!identifier.match(plan_id).hasMatch() || identity_.device_token.isEmpty())
        return;
    request("DELETE", QStringLiteral("/api/v2/media-plans/%1/activation").arg(plan_id),
            nullptr, true, [](int, const QJsonObject &) {}, true);
}

void ClientController::stopAll()
{
    cancelTalk();
    finalize_pending_recordings();
    grid_streams_.clear();
    focus_streams_.clear();
    studio_preview_streams_.clear();
    studio_program_streams_.clear();
    live_topology_ = QStringLiteral("off");
    emit topologyChanged();
}

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

bool ClientController::startManualRecording(bool focused, const QString &session_id,
                                            const QString &path)
{
    const auto context = (focused ? focus_streams_ : grid_streams_).context(session_id);
    if (!context || !cameraHasPermission(context->camera_id, QStringLiteral("record-local"))) {
        emit userError(QStringLiteral("This device grant does not permit local recording"));
        return false;
    }
    const bool started = (focused ? focus_streams_ : grid_streams_).startRecording(session_id, path);
    if (started)
        pending_recordings_.insert(QStringLiteral("%1:%2").arg(focused ?
            QStringLiteral("focus") : QStringLiteral("grid"), session_id), path);
    return started;
}

void ClientController::stopManualRecording(bool focused, const QString &session_id)
{
    (focused ? focus_streams_ : grid_streams_).stopRecording(session_id);
    const QString key = QStringLiteral("%1:%2").arg(focused ?
        QStringLiteral("focus") : QStringLiteral("grid"), session_id);
    const QString path = pending_recordings_.take(key);
    if (!path.isEmpty() && QFileInfo(path).isFile())
        set_last_capture_path(path);
}

void ClientController::setListening(bool focused, const QString &session_id, bool enabled)
{
    (focused ? focus_streams_ : grid_streams_).setMuted(session_id, !enabled);
}

bool ClientController::cameraHasPermission(const QString &camera_id, const QString &permission) const
{
    static const QStringList allowed{QStringLiteral("view"), QStringLiteral("ptz"),
        QStringLiteral("talk"), QStringLiteral("snapshot"), QStringLiteral("record-local")};
    if (!allowed.contains(permission))
        return false;
    const QVariantList permissions = camera(camera_id).value(QStringLiteral("permissions")).toList();
    return std::any_of(permissions.begin(), permissions.end(), [&permission](const QVariant &value) {
        return value.toString() == permission;
    });
}

void ClientController::camera_operation(const QString &camera_id, const QString &operation,
                                        const QJsonObject *body, ReplyHandler handler)
{
    if (camera_id.isEmpty() || !QRegularExpression(QStringLiteral("^[A-Za-z0-9._-]{1,64}$"))
                                    .match(camera_id).hasMatch()) {
        emit userError(QStringLiteral("Camera ID is invalid"));
        return;
    }
    const QByteArray method = operation == QStringLiteral("presets") ? "GET" : "POST";
    request(method, QStringLiteral("/api/v2/client/cameras/%1/%2").arg(camera_id, operation),
            body, true, std::move(handler));
}

void ClientController::movePtz(const QString &camera_id, qreal x, qreal y, qreal zoom)
{
    if (!cameraHasPermission(camera_id, QStringLiteral("ptz"))) {
        emit userError(QStringLiteral("This device grant does not permit PTZ"));
        return;
    }
    QJsonObject body{{QStringLiteral("operation"), QStringLiteral("continuous")},
        {QStringLiteral("x"), std::clamp(x, -1.0, 1.0)},
        {QStringLiteral("y"), std::clamp(y, -1.0, 1.0)},
        {QStringLiteral("zoom"), std::clamp(zoom, -1.0, 1.0)},
        {QStringLiteral("durationMs"), 500}};
    camera_operation(camera_id, QStringLiteral("ptz"), &body,
        [this](int status, const QJsonObject &) {
            if (status < 200 || status >= 300)
                emit userError(QStringLiteral("PTZ command was rejected"));
        });
}

void ClientController::stopPtz(const QString &camera_id)
{
    if (!cameraHasPermission(camera_id, QStringLiteral("ptz")))
        return;
    QJsonObject body{{QStringLiteral("operation"), QStringLiteral("stop")}};
    camera_operation(camera_id, QStringLiteral("ptz"), &body,
        [this](int status, const QJsonObject &) {
            if (status < 200 || status >= 300)
                emit userError(QStringLiteral("PTZ stop command was rejected"));
        });
}

void ClientController::saveSnapshot(const QString &camera_id, const QString &absolute_path)
{
    if (!cameraHasPermission(camera_id, QStringLiteral("snapshot"))) {
        emit userError(QStringLiteral("This device grant does not permit snapshots"));
        return;
    }
    if (!QFileInfo(absolute_path).isAbsolute()) {
        emit userError(QStringLiteral("Snapshot target must be an absolute path"));
        return;
    }
    camera_operation(camera_id, QStringLiteral("snapshot"), nullptr,
        [this, absolute_path](int status, const QJsonObject &response) {
            if (status != 200) {
                emit userError(QStringLiteral("Snapshot request was rejected"));
                return;
            }
            const QString content_type = response.value(QStringLiteral("contentType")).toString();
            const QByteArray encoded = response.value(QStringLiteral("data")).toString().toLatin1();
            const QByteArray bytes = QByteArray::fromBase64(encoded, QByteArray::AbortOnBase64DecodingErrors);
            const QByteArray expected = response.value(QStringLiteral("sha256")).toString().toLatin1();
            const QByteArray observed = QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex();
            if ((content_type != QStringLiteral("image/jpeg") && content_type != QStringLiteral("image/png")) ||
                bytes.isEmpty() || bytes.size() > 16 * 1024 * 1024 || expected.size() != 64 ||
                expected != observed) {
                emit userError(QStringLiteral("Camera returned an invalid or corrupted snapshot"));
                return;
            }
            QSaveFile file(absolute_path);
            if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size() || !file.commit()) {
                emit userError(QStringLiteral("Snapshot could not be saved to the selected path"));
                return;
            }
            set_last_capture_path(absolute_path);
            emit operationCompleted(QStringLiteral("Snapshot saved"));
        });
}

void ClientController::saveLocalScreenshot(const QString &camera_id, QObject *visual_item,
                                           const QString &absolute_path)
{
    if (!cameraHasPermission(camera_id, QStringLiteral("snapshot"))) {
        emit userError(QStringLiteral("This device grant does not permit screenshots"));
        return;
    }
    auto *item = qobject_cast<QQuickItem *>(visual_item);
    const QFileInfo target(absolute_path);
    const QString suffix = target.suffix().toLower();
    if (!item || !target.isAbsolute() || target.exists() ||
        !QStringList{QStringLiteral("jpg"), QStringLiteral("png")}.contains(suffix) ||
        !QDir(target.absolutePath()).exists()) {
        emit userError(QStringLiteral(
            "Local screenshot requires a rendered item and a new absolute JPEG/PNG target"));
        return;
    }
    const auto capture = item->grabToImage();
    if (!capture) {
        emit userError(QStringLiteral("The decoded video surface could not be captured"));
        return;
    }
    connect(capture.data(), &QQuickItemGrabResult::ready, this,
            [this, capture, path = target.absoluteFilePath()] {
        const QImage image = capture->image();
        if (image.isNull() || image.sizeInBytes() > 64 * 1024 * 1024 ||
            !capture->saveToFile(path)) {
            QFile::remove(path);
            emit userError(QStringLiteral("The local decoded-frame screenshot could not be saved"));
            return;
        }
        set_last_capture_path(path);
        emit operationCompleted(QStringLiteral("Local decoded-frame screenshot saved"));
    });
}

QString ClientController::suggestedCapturePath(const QString &extension) const
{
    const QString suffix = QStringList{QStringLiteral("mkv"), QStringLiteral("jpg"),
        QStringLiteral("png"), QStringLiteral("mp4"), QStringLiteral("json")}.contains(extension.toLower()) ?
        extension.toLower() : QStringLiteral("mkv");
#if defined(Q_OS_ANDROID)
    const QJniObject result = QJniObject::callStaticObjectMethod(
        "org/webobs/nativeclient/WebObsActivity", "privateCapturePath",
        "(Ljava/lang/String;)Ljava/lang/String;", QJniObject::fromString(suffix).object<jstring>());
    const QString android_path = result.toString();
    if (!android_path.isEmpty())
        return android_path;
#endif
    QString directory = QStandardPaths::writableLocation(QStandardPaths::MoviesLocation);
    if (directory.isEmpty())
        directory = QDir::homePath();
    return QDir(directory).filePath(QStringLiteral("webobs-%1.%2").arg(
        QDateTime::currentDateTimeUtc().toString(QStringLiteral("yyyyMMddTHHmmssZ")), suffix));
}

bool ClientController::talkActive() const { return talk_capture_.active(); }

void ClientController::startTalk(const QString &camera_id)
{
    if (!cameraHasPermission(camera_id, QStringLiteral("talk"))) {
        emit userError(QStringLiteral("This device grant does not permit Push-to-Talk"));
        return;
    }
#if defined(Q_OS_ANDROID)
    if (!QJniObject::callStaticMethod<jboolean>(
            "org/webobs/nativeclient/WebObsActivity", "ensureMicrophonePermission", "()Z")) {
        emit userError(QStringLiteral(
            "Microphone permission is required for Push-to-Talk; approve it and press Talk again"));
        return;
    }
#endif
    QString error;
    if (!talk_capture_.start(error)) {
        emit userError(error);
        return;
    }
    talk_camera_id_ = camera_id;
}

void ClientController::finishTalk()
{
    talk_capture_.finish();
}

void ClientController::cancelTalk()
{
    talk_capture_.cancel();
    talk_camera_id_.clear();
}

void ClientController::exportMkvToMp4(const QString &mkv_path, const QString &mp4_path)
{
    const QFileInfo input(mkv_path);
    const QFileInfo output(mp4_path);
    if (!input.isAbsolute() || !input.isFile() ||
        input.suffix().compare(QStringLiteral("mkv"), Qt::CaseInsensitive) != 0 ||
        !output.isAbsolute() || output.suffix().compare(QStringLiteral("mp4"), Qt::CaseInsensitive) != 0 ||
        output.exists() || input.absoluteFilePath() == output.absoluteFilePath() ||
        !QDir(output.absolutePath()).exists()) {
        emit userError(QStringLiteral("MP4 export requires an existing absolute MKV and a new absolute MP4 target"));
        return;
    }
    auto *process = new QProcess(this);
    process->setProgram(QStringLiteral("gst-launch-1.0"));
    process->setArguments({QStringLiteral("-q"), QStringLiteral("-e"),
        QStringLiteral("filesrc"), QStringLiteral("location=%1").arg(input.absoluteFilePath()),
        QStringLiteral("!"), QStringLiteral("matroskademux"), QStringLiteral("!"),
        QStringLiteral("parsebin"), QStringLiteral("!"), QStringLiteral("mp4mux"),
        QStringLiteral("faststart=true"), QStringLiteral("!"), QStringLiteral("filesink"),
        QStringLiteral("location=%1").arg(output.absoluteFilePath())});
    process->setProcessChannelMode(QProcess::ForwardedErrorChannel);
    connect(process, &QProcess::finished, this,
        [this, process, target = output.absoluteFilePath()](int exit_code, QProcess::ExitStatus status) {
            if (status == QProcess::NormalExit && exit_code == 0) {
                emit operationCompleted(QStringLiteral("Crash-safe MKV exported to MP4 without video re-encoding"));
            } else {
                QFile::remove(target);
                emit userError(QStringLiteral("MP4 remux failed; the incomplete target was removed"));
            }
            process->deleteLater();
        });
    connect(process, &QProcess::errorOccurred, this,
        [this, process, target = output.absoluteFilePath()](QProcess::ProcessError error) {
            if (error == QProcess::FailedToStart) {
                QFile::remove(target);
                emit userError(QStringLiteral("GStreamer MP4 export helper is unavailable"));
                process->deleteLater();
            }
        });
    process->start();
}

void ClientController::setMonitoringFullscreen(bool active)
{
#if defined(Q_OS_ANDROID)
    wake_lock_active_ = QJniObject::callStaticMethod<jboolean>(
        "org/webobs/nativeclient/KeyStoreBridge", "setWakeLock", "(Z)Z",
        static_cast<jboolean>(active));
    emit platformStatusChanged();
#else
    Q_UNUSED(active)
#endif
}

void ClientController::exportLastCapture()
{
#if defined(Q_OS_ANDROID)
    const QFileInfo source(last_capture_path_);
    if (!source.isAbsolute() || !source.isFile()) {
        emit userError(QStringLiteral("There is no completed private capture to export"));
        return;
    }
    QString mime = QStringLiteral("application/octet-stream");
    if (source.suffix().compare(QStringLiteral("mkv"), Qt::CaseInsensitive) == 0)
        mime = QStringLiteral("video/x-matroska");
    else if (source.suffix().compare(QStringLiteral("jpg"), Qt::CaseInsensitive) == 0)
        mime = QStringLiteral("image/jpeg");
    else if (source.suffix().compare(QStringLiteral("png"), Qt::CaseInsensitive) == 0)
        mime = QStringLiteral("image/png");
    const jboolean started = QJniObject::callStaticMethod<jboolean>(
        "org/webobs/nativeclient/WebObsActivity", "exportPrivateCapture",
        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Z",
        QJniObject::fromString(source.absoluteFilePath()).object<jstring>(),
        QJniObject::fromString(mime).object<jstring>(),
        QJniObject::fromString(source.fileName()).object<jstring>());
    if (!started)
        emit userError(QStringLiteral("The private capture was rejected by the Android export boundary"));
#else
    emit userError(QStringLiteral("Storage Access Framework export is available only on Android"));
#endif
}

void ClientController::refresh_platform_status()
{
#if defined(Q_OS_ANDROID)
    const int decoder_instances = QJniObject::callStaticMethod<jint>(
        "org/webobs/nativeclient/WebObsActivity", "hardwareVideoDecoderInstances", "()I");
    const bool wake_lock = QJniObject::callStaticMethod<jboolean>(
        "org/webobs/nativeclient/KeyStoreBridge", "wakeLockHeld", "()Z");
    const QString network = QJniObject::callStaticObjectMethod(
        "org/webobs/nativeclient/WebObsActivity", "networkStatus", "()Ljava/lang/String;").toString();
    const QString thermal = QJniObject::callStaticObjectMethod(
        "org/webobs/nativeclient/WebObsActivity", "thermalStatus", "()Ljava/lang/String;").toString();
    const QString export_status = QJniObject::callStaticObjectMethod(
        "org/webobs/nativeclient/WebObsActivity", "consumeExportStatus", "()Ljava/lang/String;").toString();
    const bool network_changed = network_status_ != QStringLiteral("unknown") &&
                                 network != network_status_;
    const bool changed = decoder_instances != hardware_decoder_instances_ ||
                         wake_lock != wake_lock_active_ || network != network_status_ ||
                         thermal != thermal_status_;
    hardware_decoder_instances_ = decoder_instances;
    wake_lock_active_ = wake_lock;
    network_status_ = network.isEmpty() ? QStringLiteral("unknown") : network;
    thermal_status_ = thermal.isEmpty() ? QStringLiteral("unknown") : thermal;
    if (changed)
        emit platformStatusChanged();
    if (network_changed && grant_.expires_at > QDateTime::currentSecsSinceEpoch()) {
        fallback_reason_ = QStringLiteral(
            "Network changed to %1; direct reachability is being re-evaluated").arg(network_status_);
        emit topologyChanged();
        grid_streams_.suspend();
        focus_streams_.suspend();
        grid_streams_.resume();
        focus_streams_.resume();
        if (!server_url_.isEmpty())
            bootstrap_internal(true);
    }
    if (export_status == QStringLiteral("complete"))
        emit operationCompleted(QStringLiteral(
            "Capture exported through Android Storage Access Framework"));
    else if (export_status == QStringLiteral("failed"))
        emit userError(QStringLiteral("Android document provider could not export the capture"));
#endif
}

void ClientController::set_last_capture_path(const QString &path)
{
    if (last_capture_path_ == path)
        return;
    last_capture_path_ = path;
    emit lastCapturePathChanged();
}

void ClientController::finalize_pending_recordings()
{
    const auto pending = pending_recordings_;
    pending_recordings_.clear();
    for (auto item = pending.cbegin(); item != pending.cend(); ++item) {
        const bool focused = item.key().startsWith(QStringLiteral("focus:"));
        const QString session_id = item.key().section(QLatin1Char(':'), 1);
        (focused ? focus_streams_ : grid_streams_).stopRecording(session_id);
        if (QFileInfo(item.value()).isFile())
            set_last_capture_path(item.value());
    }
}

void ClientController::persist_identity()
{
    QString warning;
    QByteArray serialized = identity_.serialize();
    const bool saved = secure_store_.save(serialized, warning);
    if (!serialized.isEmpty())
        sodium_memzero(serialized.data(), static_cast<size_t>(serialized.size()));
    if (!saved)
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
StreamSessionModel *ClientController::gridStreams() { return &grid_streams_; }
StreamSessionModel *ClientController::focusStreams() { return &focus_streams_; }
StreamSessionModel *ClientController::studioPreviewStreams() { return &studio_preview_streams_; }
StreamSessionModel *ClientController::studioProgramStreams() { return &studio_program_streams_; }
int ClientController::gridCapacity() const { return grid_capacity_; }
SceneModel *ClientController::scene() { return studio_.preview(); }
StudioWorkspace *ClientController::studio() { return &studio_; }
bool ClientController::androidPlatform() const
{
#if defined(Q_OS_ANDROID)
    return true;
#else
    return false;
#endif
}
int ClientController::hardwareDecoderInstances() const { return hardware_decoder_instances_; }
bool ClientController::grid16Available() const
{
#if defined(Q_OS_ANDROID)
    return hardware_decoder_instances_ >= 16 &&
           !QStringList{QStringLiteral("severe"), QStringLiteral("critical"),
                        QStringLiteral("emergency"), QStringLiteral("shutdown")}
                .contains(thermal_status_);
#else
    return true;
#endif
}
bool ClientController::wakeLockActive() const { return wake_lock_active_; }
QString ClientController::networkStatus() const { return network_status_; }
QString ClientController::thermalStatus() const { return thermal_status_; }
QString ClientController::lastCapturePath() const { return last_capture_path_; }

}
