#include "config_backup.hpp"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSaveFile>

#include <algorithm>
#include <vector>

namespace webobs::native_host {
namespace {
constexpr int keep_backups = 3;

QList<QFileInfo> backup_dirs(const QDir &backups)
{
	return backups.entryInfoList({QStringLiteral("config-*")}, QDir::Dirs | QDir::NoDotAndDotDot, QDir::Name);
}

bool has_backup_for_version(const QDir &backups, const QString &version)
{
	for (const auto &info : backup_dirs(backups)) {
		QFile receipt(info.absoluteFilePath() + QStringLiteral("/backup.json"));
		if (!receipt.open(QIODevice::ReadOnly))
			continue;
		const auto object = QJsonDocument::fromJson(receipt.readAll()).object();
		if (object.value(QStringLiteral("version")).toString() == version)
			return true;
	}
	return false;
}

void prune_old_backups(const QDir &backups)
{
	auto dirs = backup_dirs(backups);
	std::sort(dirs.begin(), dirs.end(), [](const QFileInfo &a, const QFileInfo &b) {
		return a.fileName() > b.fileName();
	});
	const int count = static_cast<int>(dirs.size());
	for (int i = keep_backups; i < count; ++i)
		QDir(dirs.at(i).absoluteFilePath()).removeRecursively();
}

bool copy_profile(const QDir &config, const QDir &destination, QJsonArray &entries, qint64 &total_bytes)
{
	const QDir config_root(config.absolutePath());
	std::vector<QJsonObject> collected;
	QDirIterator iterator(config_root.absolutePath(), QDir::Files | QDir::Hidden, QDirIterator::Subdirectories);
	while (iterator.hasNext()) {
		iterator.next();
		const QFileInfo info = iterator.fileInfo();
		if (info.isSymLink())
			return false;
		QString relative = config_root.relativeFilePath(info.absoluteFilePath());
		relative.replace(QLatin1Char('\\'), QLatin1Char('/'));
		if (relative.isEmpty() || relative.startsWith(QStringLiteral("..")) ||
		    QDir::isAbsolutePath(relative))
			return false;
		// OBS appends to its own logs during startup and drops per-run sentinel
		// files; neither is user configuration, and restoring a stale sentinel
		// could look like a crash. Crash dumps are private and not needed either.
		if (relative.startsWith(QStringLiteral("obs-studio/logs/")) ||
		    relative.startsWith(QStringLiteral("obs-studio/.sentinel/")) ||
		    relative.startsWith(QStringLiteral("obs-studio/crashes/")))
			continue;
		QFile source(info.absoluteFilePath());
		if (!source.open(QIODevice::ReadOnly))
			return false;
		const QByteArray data = source.read(64LL * 1024 * 1024 + 1);
		if (source.error() != QFileDevice::NoError || data.size() > 64LL * 1024 * 1024)
			return false;
		const QString target = destination.absoluteFilePath(relative);
		if (!QDir().mkpath(QFileInfo(target).absolutePath()))
			return false;
		QFile output(target);
		if (!output.open(QIODevice::WriteOnly | QIODevice::Truncate) || output.write(data) != data.size())
			return false;
		output.close();
		const QString source_hash =
			QString::fromLatin1(QCryptographicHash::hash(data, QCryptographicHash::Sha256).toHex());
		collected.push_back(QJsonObject{{QStringLiteral("path"), relative},
		                                {QStringLiteral("bytes"), data.size()},
		                                {QStringLiteral("sha256"), source_hash}});
		total_bytes += data.size();
	}
	std::sort(collected.begin(), collected.end(),
	          [](const QJsonObject &a, const QJsonObject &b) {
		          return a.value(QStringLiteral("path")).toString() <
		                 b.value(QStringLiteral("path")).toString();
	          });
	for (const auto &entry : collected)
		entries.append(entry);
	return true;
}
} // namespace

void backup_config_for_upgrade_if_needed()
{
	const QDir bin(QCoreApplication::applicationDirPath());
	const QString root = QDir::cleanPath(bin.absoluteFilePath(QStringLiteral("../..")));
	const QString config_path = root + QStringLiteral("/config");
	if (!QFileInfo(config_path + QStringLiteral("/obs-studio")).isDir())
		return;

	QFile manifest(root + QStringLiteral("/webobs-native-prototype.json"));
	if (!manifest.open(QIODevice::ReadOnly))
		return;
	const QString version =
		QJsonDocument::fromJson(manifest.readAll()).object().value(QStringLiteral("version")).toString();
	manifest.close();
	if (!QRegularExpression(QStringLiteral("^[0-9A-Za-z._-]{1,40}$")).match(version).hasMatch())
		return;

	const QString backups_path = root + QStringLiteral("/backups");
	QDir backups(backups_path);
	if (backups.exists() && has_backup_for_version(backups, version))
		return;
	if (!QDir().mkpath(backups_path))
		return;

	const QString stamp =
		QDateTime::currentDateTimeUtc().toString(QStringLiteral("yyyyMMdd'T'HHmmss'Z'"));
	QDir destination(backups_path + QStringLiteral("/config-") + version + QLatin1Char('-') + stamp);
	if (!QDir().mkpath(destination.absolutePath()))
		return;

	QJsonArray entries;
	qint64 total_bytes = 0;
	const bool copied =
		copy_profile(QDir(config_path), destination, entries, total_bytes);
	QJsonObject receipt{{QStringLiteral("schema"), 1},
	                    {QStringLiteral("kind"), QStringLiteral("native-config-upgrade-backup")},
	                    {QStringLiteral("version"), version},
	                    {QStringLiteral("createdAt"),
	                     QDateTime::currentDateTimeUtc().toString(Qt::ISODate)},
	                    {QStringLiteral("source"), QStringLiteral("config")},
	                    {QStringLiteral("files"), entries.size()},
	                    {QStringLiteral("bytes"), total_bytes},
	                    {QStringLiteral("entries"), entries}};
	if (copied) {
		const QByteArray payload = QJsonDocument(receipt).toJson();
		QSaveFile file(destination.absoluteFilePath(QStringLiteral("backup.json")));
		if (file.open(QIODevice::WriteOnly) && file.write(payload) == payload.size() &&
		    file.commit())
			prune_old_backups(backups);
		else
			destination.removeRecursively();
	} else {
		destination.removeRecursively();
	}
}
} // namespace webobs::native_host
