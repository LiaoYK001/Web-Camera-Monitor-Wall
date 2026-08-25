#pragma once

#include <QString>

class QGuiApplication;

namespace webobs::client {

int run_batch_probe(QGuiApplication &application, const QString &manifest_path, QString &error);

}
