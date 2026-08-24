#pragma once

#include <QJsonObject>
#include <QString>

namespace webobs::client {

struct TopologyPlan {
    int contract_version = 0;
    QString plan_id;
    QString camera_id;
    QString profile_id;
    QString status;
    QString topology;
    QString receiver_kind;
    QString archive_topology;
    QString decoder;
    QString renderer;
    QString encoder;
    QString upstream_owner;
    bool live_server_media_expected = true;
    QString fallback_reason;
    qint64 expires_at = 0;

    static TopologyPlan from_json(const QJsonObject &value, QString &error);
    [[nodiscard]] bool true_direct() const;
};

}
