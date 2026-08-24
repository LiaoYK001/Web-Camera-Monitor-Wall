#include "webobs/client/topology_plan.hpp"

#include <QSet>

namespace webobs::client {

TopologyPlan TopologyPlan::from_json(const QJsonObject &value, QString &error)
{
    TopologyPlan result;
    const QSet<QString> topologies{"true-direct", "gateway-direct", "hybrid", "composite"};
    const QSet<QString> receivers{"native", "browser"};
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
    if (result.contract_version != 1 || result.plan_id.size() != 32 ||
        result.camera_id.isEmpty() || result.profile_id.isEmpty() ||
        !topologies.contains(result.topology) || !receivers.contains(result.receiver_kind) ||
        result.expires_at <= 0) {
        error = QStringLiteral("TopologyPlan contract is invalid");
        return {};
    }
    if (result.topology == QStringLiteral("true-direct") && result.live_server_media_expected) {
        error = QStringLiteral("true-direct plan unexpectedly requires server media");
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
