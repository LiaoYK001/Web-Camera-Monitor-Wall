#include "product_http_client.hpp"
#include <QJsonDocument>
#include <QNetworkCookie>
#include <QNetworkProxy>
#include <QNetworkReply>
#include <QRegularExpression>
#include <QTimer>
#include <memory>

namespace webobs::native_host {
ProductHttpClient::ProductHttpClient(QUrl origin, QByteArray host_secret, QObject *parent)
	: QObject(parent), network_(this), origin_(std::move(origin)), host_secret_(std::move(host_secret))
{
	network_.setProxy(QNetworkProxy::NoProxy);
	configured_ = origin_.scheme() == "http" && origin_.host() == "127.0.0.1" && origin_.port() > 0 &&
		origin_.userInfo().isEmpty() && origin_.path().isEmpty() && !origin_.hasQuery() && !origin_.hasFragment() &&
		QRegularExpression("^[a-f0-9]{64}$").match(QString::fromLatin1(host_secret_)).hasMatch();
}

ProductHttpClient::~ProductHttpClient()
{
	// Abort cannot dispatch callbacks into an owning widget during destruction.
	for (auto *reply : network_.findChildren<QNetworkReply *>()) {
		QObject::disconnect(reply, nullptr, this, nullptr);
		reply->abort();
	}
}

void ProductHttpClient::reset_session()
{
	++generation_;
	session_cookie_.clear();
}

void ProductHttpClient::request(const QString &path, const QByteArray &method, const QJsonObject &body,
	Reply callback, int timeout_ms)
{
	if (path == "/api/v1/native/auth/login" && method == "POST") reset_session();
	const auto encoded = QJsonDocument(body).toJson(QJsonDocument::Compact);
	if (!configured_ || (method != "GET" && method != "POST") || timeout_ms < 1 || timeout_ms > 12000 ||
	    pending_.size() >= 16 || encoded.size() > 16384 || !path.startsWith("/api/v1/")) {
		callback(0, {});
		return;
	}
	const auto generation = generation_;
	QUrl url = origin_;
	url.setPath(path);
	QNetworkRequest message(url);
	message.setRawHeader("Origin", origin_.toString(QUrl::RemovePath).toUtf8());
	message.setRawHeader("X-WebOBS-Native-Host", host_secret_);
	message.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
	message.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::ManualRedirectPolicy);
	// A late reply must not mutate a newer session through QNAM's cookie jar.
	// Only an accepted login of the current generation may change our cookie.
	message.setAttribute(QNetworkRequest::CookieLoadControlAttribute, QNetworkRequest::Manual);
	message.setAttribute(QNetworkRequest::CookieSaveControlAttribute, QNetworkRequest::Manual);
	if (!session_cookie_.isEmpty()) message.setRawHeader("Cookie", session_cookie_);
	message.setTransferTimeout(timeout_ms);
	auto *reply = method == "GET" ? network_.get(message) : network_.post(message, encoded);
	pending_.insert(reply);
	reply->setReadBufferSize(response_limit);
	auto *deadline = new QTimer(reply);
	deadline->setSingleShot(true);
	connect(deadline, &QTimer::timeout, reply, &QNetworkReply::abort);
	deadline->start(timeout_ms);
	auto bytes = std::make_shared<QByteArray>();
	connect(reply, &QNetworkReply::readyRead, this, [reply, bytes] {
		if (reply->bytesAvailable() > response_limit - bytes->size()) {
			reply->abort();
			return;
		}
		bytes->append(reply->readAll());
	});
	connect(reply, &QNetworkReply::finished, this, [this, reply, bytes, deadline, generation, path, callback] {
		deadline->stop();
		pending_.remove(reply);
		const int code = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
		const auto document = QJsonDocument::fromJson(*bytes);
		const bool valid = reply->error() == QNetworkReply::NoError && document.isObject();
		int result_code = valid ? code : (code >= 400 ? code : 0);
		if (generation == generation_ && path == "/api/v1/native/auth/login" && result_code == 200) {
			int count = 0;
			for (const auto &header : reply->rawHeaderPairs())
				count += header.first.compare("Set-Cookie", Qt::CaseInsensitive) == 0;
			const auto header = reply->rawHeader("Set-Cookie");
			const auto cookies = header.size() <= 1024 ? QNetworkCookie::parseCookies(header) : QList<QNetworkCookie>{};
			if (count != 1 || cookies.size() != 1 || cookies[0].name() != "webobs_session" ||
			    !cookies[0].isHttpOnly() || cookies[0].isSecure() || !cookies[0].domain().isEmpty() ||
			    cookies[0].path() != "/" ||
			    !QRegularExpression("^[a-f0-9]{64}$").match(QString::fromLatin1(cookies[0].value())).hasMatch()) {
				session_cookie_.clear();
				result_code = 0;
			} else {
				session_cookie_ = cookies[0].name() + '=' + cookies[0].value();
			}
		}
		reply->deleteLater();
		if (generation == generation_) callback(result_code, document.object());
	});
}
} // namespace webobs::native_host
