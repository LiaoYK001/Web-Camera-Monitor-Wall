#pragma once

#include <cstdint>

namespace webobs::native_host {

// The adapter owning OBS's actual graphics device. This is rendering evidence,
// NOT per-source hardware-decoding evidence and NOT a performance measurement.
struct RendererDevice {
	bool available = false;
	std::uint32_t luid_high = 0, luid_low = 0;
	std::uint32_t vendor_id = 0, device_id = 0;
	bool software = false;
	std::uint64_t dedicated_video_memory = 0;
};

// Call after OBS graphics initialization. Enters/leaves the OBS graphics context,
// retains no handles and makes no adapter-selection or source-setting changes.
RendererDevice observe_renderer_device();

} // namespace webobs::native_host
