#include "webobs/client/network_policy.hpp"

#include <QHostAddress>
#include <QNetworkInterface>
#include <QUrl>

namespace webobs::client {

QString classify_network(const QString &endpoint)
{
    const QString host = QUrl(endpoint).host().toLower();
    QHostAddress address;
    if (address.setAddress(host)) {
        bool ipv4 = false;
        const quint32 value = address.toIPv4Address(&ipv4);
        if (address.isLoopback() || address.isLinkLocal() ||
            (ipv4 && ((value & 0xff000000U) == 0x0a000000U ||
                      (value & 0xfff00000U) == 0xac100000U ||
                      (value & 0xffff0000U) == 0xc0a80000U)) ||
            (!ipv4 && (host.startsWith(QStringLiteral("fc")) ||
                       host.startsWith(QStringLiteral("fd")))))
            return QStringLiteral("lan");
    } else if (host == QStringLiteral("localhost") || host.endsWith(QStringLiteral(".local")) ||
               (!host.isEmpty() && !host.contains('.'))) {
        return QStringLiteral("lan");
    }
    if (!address.isNull()) {
        for (const QNetworkInterface &interface : QNetworkInterface::allInterfaces()) {
            const QString name = (interface.name() + QLatin1Char(' ') +
                                  interface.humanReadableName()).toLower();
            const bool tailscale = name.contains(QStringLiteral("tailscale"));
            const bool vpn_interface = tailscale || name.contains(QStringLiteral("wireguard")) ||
                                       name.startsWith(QStringLiteral("tun")) ||
                                       name.startsWith(QStringLiteral("wg"));
            if (!interface.flags().testFlag(QNetworkInterface::IsUp) || !vpn_interface)
                continue;
            bool target_ipv4 = false;
            const quint32 target = address.toIPv4Address(&target_ipv4);
            if (tailscale && target_ipv4 && (target & 0xffc00000U) == 0x64400000U)
                return QStringLiteral("vpn");
            for (const QNetworkAddressEntry &entry : interface.addressEntries()) {
                if (entry.prefixLength() > 0 && address.isInSubnet(entry.ip(), entry.prefixLength()))
                    return QStringLiteral("vpn");
            }
        }
    }
    return QStringLiteral("wan");
}

}
