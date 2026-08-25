#include "webobs/client/topology_plan.hpp"

#include <QHash>
#include <QRegularExpression>
#include <QSet>

namespace webobs::client {

TopologyPlan TopologyPlan::from_json(const QJsonObject &value, QString &error)
{
    TopologyPlan result;
    const QSet<QString> topologies{"true-direct", "gateway-direct", "hybrid", "composite"};
    const QSet<QString> receivers{"native", "browser"};
    const QSet<QString> statuses{"active", "rejected"};
    const QSet<QString> archives{"off", "server-copy", "server-transcode", "local-manual"};
    const QSet<QString> fields{"contractVersion", "planId", "cameraId", "profileId", "status",
        "topology", "receiverKind", "archiveTopology", "decoder", "renderer", "encoder",
        "upstreamOwner", "liveServerMediaExpected", "fallbackReason", "expiresAt"};
    result.contract_version = value.value("contractVersion").toInt();
    result.plan_id = value.value("planId").toString();
    result.camera_id = value.value("cameraId").toString();
    result.profile_id = value.value("profileId").toString();
    result.status = value.value("status").toString();
    result.topology = value.value("topology").toString();
    result.receiver_kind = value.value("receiverKind").toString();
    result.archive_topology = value.value("archiveTopology").toString();
    result.decoder = value.value("decoder").toString();
    result.renderer = value.value("renderer").toString();
    result.encoder = value.value("encoder").toString();
    result.upstream_owner = value.value("upstreamOwner").toString();
    result.live_server_media_expected = value.value("liveServerMediaExpected").toBool(true);
    result.fallback_reason = value.value("fallbackReason").toString();
    result.expires_at = value.value("expiresAt").toInteger();
    static const QRegularExpression plan_identifier(QStringLiteral("^[0-9a-f]{32}$"));
    static const QRegularExpression stable_identifier(QStringLiteral("^[A-Za-z0-9._-]{1,64}$"));
    const QStringList keys = value.keys();
    const QSet<QString> actual_fields(keys.cbegin(), keys.cend());
    const bool bounded_text = result.decoder.size() <= 64 && !result.decoder.isEmpty() &&
        result.renderer.size() <= 64 && !result.renderer.isEmpty() &&
        result.encoder.size() <= 64 && !result.encoder.isEmpty() &&
        result.upstream_owner.size() <= 96 && !result.upstream_owner.isEmpty() &&
        result.fallback_reason.size() <= 256;
    if (actual_fields != fields || result.contract_version != 1 ||
        !plan_identifier.match(result.plan_id).hasMatch() ||
        !stable_identifier.match(result.camera_id).hasMatch() ||
        !stable_identifier.match(result.profile_id).hasMatch() ||
        !statuses.contains(result.status) || !topologies.contains(result.topology) ||
        !receivers.contains(result.receiver_kind) || !archives.contains(result.archive_topology) ||
        !bounded_text || result.expires_at <= 0) {
        error = QStringLiteral("TopologyPlan contract is invalid");
        return {};
    }
    const QHash<QString, QString> owners{
        {QStringLiteral("gateway-direct"), QStringLiteral("docker:mediamtx")},
        {QStringLiteral("hybrid"), QStringLiteral("docker:transcoder")},
        {QStringLiteral("composite"), QStringLiteral("docker:libobs")}};
    const QHash<QString, QString> encoders{
        {QStringLiteral("true-direct"), QStringLiteral("none")},
        {QStringLiteral("gateway-direct"), QStringLiteral("none")},
        {QStringLiteral("hybrid"), QStringLiteral("track-converter")},
        {QStringLiteral("composite"), QStringLiteral("obs-program")}};
    const bool direct = result.topology == QStringLiteral("true-direct");
    const bool owner_valid = direct ?
        QRegularExpression(QStringLiteral("^client:[0-9a-f]{32}$"))
            .match(result.upstream_owner).hasMatch() :
        result.upstream_owner == owners.value(result.topology);
    if (!owner_valid || result.encoder != encoders.value(result.topology) ||
        result.live_server_media_expected == direct ||
        (result.status == QStringLiteral("rejected") && result.fallback_reason.isEmpty()) ||
        (result.status == QStringLiteral("active") && direct && !result.fallback_reason.isEmpty())) {
        error = QStringLiteral("TopologyPlan media ownership contract is invalid");
        return {};
    }
    return result;
}

bool TopologyPlan::true_direct() const
{
    return status == QStringLiteral("active") && topology == QStringLiteral("true-direct") &&
           !live_server_media_expected;
}

}
