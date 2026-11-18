// Real Qt HTTP/event-loop regression for the supervisor's LAN sharing switch.
// This is transport and fail-closed evidence only: no Caddy, certificate,
// camera, LAN interface or installed product is involved.
#include "product_lan.hpp"
#include <QCoreApplication>
#include <QEventLoop>
#include <QHostAddress>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTimer>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
using webobs::native_host::ProductLanSwitch;
const QByteArray secret(64, 'a');
void require(bool value, const char *message) { if (!value) throw std::runtime_error(message); }

void pause(int ms)
{
	QEventLoop loop;
	QTimer::singleShot(ms, &loop, &QEventLoop::quit);
	loop.exec();
}

struct Fixture {
	QTcpServer server;
	QByteArray requests;
	int connections = 0, next_code = 200;
	QByteArray next_body = R"({"enabled":false,"port":18443,"urls":[],"running":false,"pendingRestart":false})";
	bool oversized = false, send_json = true, failed = false;
	Fixture()
	{
		require(server.listen(QHostAddress::LocalHost, 0), "fixture listen failed");
		QObject::connect(&server, &QTcpServer::newConnection, &server, [this] {
			while (auto *socket = server.nextPendingConnection()) {
				++connections;
				auto bytes = std::make_shared<QByteArray>();
				QObject::connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
				QObject::connect(socket, &QTcpSocket::readyRead, &server, [this, socket, bytes] {
					bytes->append(socket->readAll());
					const auto end = bytes->indexOf("\r\n\r\n");
					if (end < 0) return;
					requests.append(bytes->left(end));
					if (requests.contains("Cookie:")) { failed = true; socket->disconnectFromHost(); return; }
					QByteArray body;
					if (!oversized && send_json) body = next_body;
					const QByteArray head = "HTTP/1.1 " + QByteArray::number(oversized ? 200 : next_code) +
						" OK\r\nContent-Type: application/json\r\n";
					const QByteArray payload = oversized
						? QByteArray("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n") +
						  QByteArray(ProductLanSwitch::response_limit + 4096, 'x')
						: head + "Content-Length: " + QByteArray::number(body.size()) +
						  "\r\nConnection: close\r\n\r\n" + body;
					socket->write(payload);
					socket->disconnectFromHost();
				});
			}
		});
	}
	int port() const { return server.serverPort(); }
};

QUrl endpoint(int port)
{
	return QUrl(QString("http://127.0.0.1:%1/lan").arg(port));
}

int exchange(Fixture &fixture, ProductLanSwitch &client, const QByteArray &method, const QJsonObject &body)
{
	fixture.requests.clear();
	bool answered = false;
	int code = -1;
	client.request(method, body, [&answered, &code](int result, const QJsonObject &) {
		code = result;
		answered = true;
	});
	QEventLoop loop;
	QTimer poll;
	QObject::connect(&poll, &QTimer::timeout, &loop, [&loop, &answered] {
		if (answered)
			loop.quit();
	});
	poll.start(20);
	QTimer::singleShot(3000, &loop, &QEventLoop::quit);
	loop.exec();
	poll.stop();
	require(answered, "the LAN switch never answered");
	return code;
}
} // namespace

int main(int argc, char **argv)
{
	QCoreApplication app(argc, argv);
	try {
		Fixture fixture;
		// Fail closed on every address that is not this boot's loopback switch.
		for (const auto &unsafe : {QUrl("http://127.0.0.1/lan"), QUrl("https://127.0.0.1:18443/lan"),
			QUrl("http://localhost:18443/lan"), QUrl("http://127.0.0.1:18443/"),
			QUrl("http://127.0.0.1:18443/lan?token=x"), QUrl("http://10.0.0.8:18443/lan"),
			QUrl("http://a@127.0.0.1:18443/lan")}) {
			ProductLanSwitch refusal(unsafe, secret);
			require(!refusal.usable(), "unsafe LAN endpoint was accepted");
			int code = -1;
			refusal.request("GET", {}, [&code](int result, const QJsonObject &) { code = result; });
			require(code == 0, "unsafe LAN endpoint still attempted a request");
		}
		ProductLanSwitch short_secret(endpoint(fixture.port()), QByteArray(63, 'a'));
		require(!short_secret.usable(), "a malformed host token was accepted");

		ProductLanSwitch client(endpoint(fixture.port()), secret);
		require(client.usable(), "the loopback LAN switch was refused");
		require(exchange(fixture, client, "GET", {}) == 200, "LAN status read failed");
		require(fixture.requests.contains("GET /lan HTTP/1.1"), "LAN status is not a plain GET");
		require(fixture.requests.contains("X-WebOBS-Native-Token: " + secret), "host token was not supplied");
		require(!fixture.requests.contains("Cookie:"), "the LAN switch request carried a session cookie");

		fixture.next_body = R"({"enabled":true,"port":18443,"urls":["https://192.168.1.9:18443"],
			"running":false,"pendingRestart":true})";
		require(exchange(fixture, client, "POST", QJsonObject{{"enabled", true}, {"port", 18443}}) == 200,
			"LAN share toggle failed");
		require(fixture.requests.contains("POST /lan HTTP/1.1"), "LAN toggle is not a POST");
		require(fixture.requests.contains("Content-Type: application/json"), "toggle has no JSON content type");

		fixture.next_code = 401;
		fixture.next_body = R"({"error":"unauthorized"})";
		require(exchange(fixture, client, "POST", QJsonObject{{"enabled", false}, {"port", 18443}}) == 401,
			"an unauthenticated LAN toggle was not reported");

		fixture.next_code = 500;
		fixture.next_body = QByteArray("<html>not json</html>");
		require(exchange(fixture, client, "POST", QJsonObject{{"enabled", false}, {"port", 18443}}) == 0,
			"an unreadable LAN reply was reported as a status code");

		fixture.oversized = true;
		fixture.next_code = 200;
		require(exchange(fixture, client, "GET", {}) == 0, "an oversized LAN reply was accepted");

		// A dead switch reports 0 so the window keeps the last known receipt.
		Fixture dead;
		ProductLanSwitch alone(endpoint(dead.port()), secret);
		dead.close();
		require(exchange(dead, alone, "GET", {}) == 0, "a closed LAN switch was reported as a status code");
	} catch (const std::exception &error) {
		std::cerr << "FAIL native LAN switch: " << error.what() << '\n';
		return 1;
	}
	std::cout << "PASS native LAN switch: unsafe endpoints, token, toggle, unreadable and oversized replies\n";
	return 0;
}
