#include "product_lan.hpp"
#include <QJsonDocument>
#include <QNetworkProxy>
#include <QNetworkReply>
#include <QRegularExpression>
#include <QTimer>
#include <memory>

namespace webobs::native_host {
ProductLanSwitch::ProductLanSwitch(QUrl endpoint, QByteArray host_secret, QObject *parent)
	: QObject(parent), network_(this), endpoint_(std::move(endpoint)), host_secret_(std::move(host_secret))
{
	network_.setProxy(QNetworkProxy::NoProxy);
	// The switch is a supervisor control, not a media gateway. Anything that is
	// not exactly the loopback /lan endpoint this boot was given stays refused.
	configured_ = endpoint_.scheme() == "http" && endpoint_.host() == "127.0.0.1" && endpoint_.port() > 0 &&
		endpoint_.path() == "/lan" && endpoint_.userInfo().isEmpty() && !endpoint_.hasQuery() &&
		!endpoint_.hasFragment() &&
		QRegularExpression("^[a-f0-9]{64}$").match(QString::fromLatin1(host_secret_)).hasMatch();
}

ProductLanSwitch::~ProductLanSwitch()
{
	// Abort cannot dispatch callbacks into an owning widget during destruction.
	for (auto *reply : network_.findChildren<QNetworkReply *>()) {
		QObject::disconnect(reply, nullptr, this, nullptr);
		reply->abort();
	}
}

void ProductLanSwitch::request(const QByteArray &method, const QJsonObject &body, Reply callback, int timeout_ms)
{
	const auto encoded = method == "POST" ? QJsonDocument(body).toJson(QJsonDocument::Compact) : QByteArray();
	if (!configured_ || (method != "GET" && method != "POST") || timeout_ms < 1 || timeout_ms > 12000 ||
	    pending_.size() >= 4 || encoded.size() > 4096) {
		callback(0, {});
		return;
	}
	QNetworkRequest message(endpoint_);
	// Same-origin from the switch's own address; the product origin policy does
	// not apply to this private loopback control, and no cookie is ever sent.
	message.setRawHeader("Origin", endpoint_.toString(QUrl::RemovePath).toUtf8());
	message.setRawHeader("X-WebOBS-Native-Token", host_secret_);
	if (method == "POST")
		message.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
	message.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::ManualRedirectPolicy);
	message.setAttribute(QNetworkRequest::CookieLoadControlAttribute, QNetworkRequest::Manual);
	message.setAttribute(QNetworkRequest::CookieSaveControlAttribute, QNetworkRequest::Manual);
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
	connect(reply, &QNetworkReply::finished, this, [this, reply, bytes, deadline, callback] {
		deadline->stop();
		pending_.remove(reply);
		const int code = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
		const auto document = QJsonDocument::fromJson(*bytes);
		// A transport failure, or a 2xx/3xx body this switch cannot parse, is reported
		// as 0 so the window keeps the last known receipt instead of guessing a new
		// state. A real HTTP error status is always reported, JSON body or not, because
		// the window must distinguish "the switch refused" from "the switch is silent".
		// Qt reports a 401/500 response as a reply error too, so the status attribute
		// decides first: any HTTP error status is surfaced, a silent transport failure
		// (no status at all) stays 0.
		const int result_code = code >= 400
			? code
			: (reply->error() == QNetworkReply::NoError && document.isObject() ? code : 0);
		reply->deleteLater();
		callback(result_code, document.isObject() ? document.object() : QJsonObject{});
	});
}
} // namespace webobs::native_host
