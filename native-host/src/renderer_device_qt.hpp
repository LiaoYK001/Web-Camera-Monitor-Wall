#pragma once
#include "renderer_device.hpp"
#include <QJsonObject>
#include <QString>

namespace webobs::native_host {
inline QJsonObject renderer_device_json(const RendererDevice &device)
{
	QJsonObject value{{"available", device.available}, {"hardwareDecodeVerified", false}};
	if (!device.available) return value;
	value.insert("api", QStringLiteral("d3d11"));
	value.insert("adapterLuid", QStringLiteral("%1:%2").arg(device.luid_high, 8, 16, QLatin1Char('0'))
		.arg(device.luid_low, 8, 16, QLatin1Char('0')));
	value.insert("vendorId", int(device.vendor_id));
	value.insert("deviceId", int(device.device_id));
	value.insert("software", device.software);
	value.insert("dedicatedVideoMemoryCapacityBytes", double(device.dedicated_video_memory));
	return value;
}
} // namespace webobs::native_host
