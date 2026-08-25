#pragma once

#include <QString>

class QGuiApplication;

namespace webobs::client {

int run_batch_probe(QGuiApplication &application, const QString &manifest_path, QString &error,
                    bool release_on_background = false,
                    bool reconnect_on_failure = false);

}
