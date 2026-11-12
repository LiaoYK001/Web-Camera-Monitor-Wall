#include "renderer_device.hpp"

#ifdef _WIN32
#include <obs.h>
#include <graphics/graphics.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <memory>

namespace {
struct GraphicsScope {
	GraphicsScope() { obs_enter_graphics(); }
	~GraphicsScope() { obs_leave_graphics(); }
};
struct ReleaseCom {
	void operator()(IUnknown *value) const { if (value) value->Release(); }
};
} // namespace
#endif

namespace webobs::native_host {

RendererDevice observe_renderer_device()
{
	RendererDevice result;
#ifdef _WIN32
	if (!obs_initialized() || !obs_get_video())
		return result;
	GraphicsScope graphics;
	if (gs_get_device_type() != GS_DEVICE_DIRECT3D_11)
		return result;
	auto *device = static_cast<ID3D11Device *>(gs_get_device_obj());
	if (!device)
		return result;
	IDXGIDevice *raw_dxgi = nullptr;
	const auto device_status = device->QueryInterface(__uuidof(IDXGIDevice), reinterpret_cast<void **>(&raw_dxgi));
	std::unique_ptr<IDXGIDevice, ReleaseCom> dxgi(raw_dxgi);
	if (FAILED(device_status) || !dxgi)
		return result;
	IDXGIAdapter *raw_adapter = nullptr;
	const auto adapter_status = dxgi->GetAdapter(&raw_adapter);
	std::unique_ptr<IDXGIAdapter, ReleaseCom> adapter(raw_adapter);
	if (FAILED(adapter_status) || !adapter)
		return result;
	IDXGIAdapter1 *raw_adapter1 = nullptr;
	const auto version_status = adapter->QueryInterface(__uuidof(IDXGIAdapter1), reinterpret_cast<void **>(&raw_adapter1));
	std::unique_ptr<IDXGIAdapter1, ReleaseCom> adapter1(raw_adapter1);
	if (FAILED(version_status) || !adapter1)
		return result;
	DXGI_ADAPTER_DESC1 description{};
	if (FAILED(adapter1->GetDesc1(&description)))
		return result;
	result.available = true;
	result.luid_high = static_cast<std::uint32_t>(description.AdapterLuid.HighPart);
	result.luid_low = description.AdapterLuid.LowPart;
	result.vendor_id = description.VendorId;
	result.device_id = description.DeviceId;
	result.software = (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0;
	result.dedicated_video_memory = description.DedicatedVideoMemory;
#endif
	return result;
}

} // namespace webobs::native_host
