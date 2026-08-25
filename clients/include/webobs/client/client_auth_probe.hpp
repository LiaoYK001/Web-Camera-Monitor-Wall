#pragma once

#include <QString>

class QGuiApplication;

namespace webobs::client {

int run_client_auth_probe(QGuiApplication &application, const QString &control_url,
                          const QString &camera_id, const QString &profile_id,
                          bool offline_after_ready, bool preserve_identity_after_ready,
                          QString &error);
int run_offline_startup_probe(QGuiApplication &application, const QString &camera_id,
                              const QString &profile_id, QString &error);

}
