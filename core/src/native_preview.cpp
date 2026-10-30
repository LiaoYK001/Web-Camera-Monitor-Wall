#include "webobs/native_preview.hpp"
#include <thread>

#ifdef _WIN32
#include <windows.h>
#include <obs.h>
#include <graphics/graphics.h>
#include <algorithm>
// Same hybrid-laptop driver hints used by the pinned OBS frontend. Windows
// per-application graphics preferences can override them; this is not HW proof.
extern "C" {
__declspec(dllexport) DWORD NvOptimusEnablement = 1;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;
}
#endif

namespace webobs {

struct NativePreview::Impl {
    explicit Impl(NativePreviewControl &value) : control(value) {}
    NativePreviewControl &control;
    std::atomic<bool> active{false};
    std::atomic<bool> stopping{false};
    std::thread thread;
#ifdef _WIN32
    HWND window = nullptr;
    obs_display_t *display = nullptr;
    bool fullscreen = false;
    RECT previous_bounds{};

    static void draw(void *data, uint32_t width, uint32_t height)
    {
        auto &self = *static_cast<Impl *>(data);
        obs_video_info info{};
        if (!obs_get_video_info(&info) || !width || !height || !info.base_width || !info.base_height) return;
        const double scale = std::min(double(width) / info.base_width, double(height) / info.base_height);
        const int cx = std::max(1, int(info.base_width * scale));
        const int cy = std::max(1, int(info.base_height * scale));
        gs_viewport_push();
        gs_projection_push();
        gs_set_viewport((int(width) - cx) / 2, (int(height) - cy) / 2, cx, cy);
        gs_ortho(0.f, float(info.base_width), 0.f, float(info.base_height), -100.f, 100.f);
        obs_render_main_texture();
        gs_projection_pop();
        gs_viewport_pop();
        self.control.frames.fetch_add(1, std::memory_order_relaxed);
    }

    void toggle_fullscreen()
    {
        if (!fullscreen) {
            GetWindowRect(window, &previous_bounds);
            MONITORINFO monitor{sizeof(MONITORINFO)};
            if (!GetMonitorInfoW(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST), &monitor)) return;
            fullscreen = true;
            SetWindowLongPtrW(window, GWL_STYLE, WS_POPUP | WS_VISIBLE);
            SetWindowPos(window, HWND_TOP, monitor.rcMonitor.left, monitor.rcMonitor.top,
                         monitor.rcMonitor.right - monitor.rcMonitor.left,
                         monitor.rcMonitor.bottom - monitor.rcMonitor.top, SWP_FRAMECHANGED);
        } else {
            fullscreen = false;
            SetWindowLongPtrW(window, GWL_STYLE, WS_OVERLAPPEDWINDOW | WS_VISIBLE);
            SetWindowPos(window, nullptr, previous_bounds.left, previous_bounds.top,
                         previous_bounds.right - previous_bounds.left,
                         previous_bounds.bottom - previous_bounds.top, SWP_FRAMECHANGED | SWP_NOZORDER);
        }
    }

    static LRESULT CALLBACK procedure(HWND handle, UINT message, WPARAM wparam, LPARAM lparam)
    {
        auto *self = reinterpret_cast<Impl *>(GetWindowLongPtrW(handle, GWLP_USERDATA));
        if (message == WM_NCCREATE) {
            self = static_cast<Impl *>(reinterpret_cast<CREATESTRUCTW *>(lparam)->lpCreateParams);
            self->window = handle;
            SetWindowLongPtrW(handle, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        }
        if (self) {
            if (message == WM_CLOSE) { self->control.requested.store(false); return 0; }
            if (message == WM_ERASEBKGND) return 1;
            if (message == WM_SIZE && self->display) {
                const bool visible = wparam != SIZE_MINIMIZED && LOWORD(lparam) && HIWORD(lparam);
                obs_display_set_enabled(self->display, visible);
                if (visible) obs_display_resize(self->display, LOWORD(lparam), HIWORD(lparam));
            }
            if (message == WM_DPICHANGED) {
                const auto &bounds = *reinterpret_cast<const RECT *>(lparam);
                SetWindowPos(handle, nullptr, bounds.left, bounds.top, bounds.right - bounds.left,
                             bounds.bottom - bounds.top, SWP_NOZORDER | SWP_NOACTIVATE);
                return 0;
            }
            if (message == WM_LBUTTONDBLCLK || (message == WM_KEYDOWN && wparam == VK_F11)) {
                self->toggle_fullscreen(); return 0;
            }
            if (message == WM_KEYDOWN && wparam == VK_ESCAPE && self->fullscreen) {
                self->toggle_fullscreen(); return 0;
            }
        }
        return DefWindowProcW(handle, message, wparam, lparam);
    }

    bool open()
    {
        WNDCLASSW type{};
        type.style = CS_DBLCLKS;
        type.lpfnWndProc = procedure;
        type.hInstance = GetModuleHandleW(nullptr);
        type.hCursor = LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
        type.lpszClassName = L"WebOBS.NativeProgram";
        if (!RegisterClassW(&type) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) return false;
        window = CreateWindowExW(0, type.lpszClassName, L"WebOBS 原生监看 · Program · F11 全屏",
                                 WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 1280, 760,
                                 nullptr, nullptr, type.hInstance, this);
        if (!window) return false;
        RECT client{};
        GetClientRect(window, &client);
        gs_init_data graphics{};
        graphics.window.hwnd = window;
        graphics.cx = std::max(1L, client.right);
        graphics.cy = std::max(1L, client.bottom);
        graphics.format = GS_BGRA;
        graphics.zsformat = GS_ZS_NONE;
        display = obs_display_create(&graphics, 0xff000000);
        if (!display) { close(); return false; }
        control.frames.store(0);
        obs_display_add_draw_callback(display, draw, this);
        ShowWindow(window, SW_SHOW);
        return true;
    }
    void close()
    {
        if (display) {
            obs_display_remove_draw_callback(display, draw, this);
            obs_display_destroy(display);
            display = nullptr;
        }
        if (window) { DestroyWindow(window); window = nullptr; }
        fullscreen = false;
    }
#endif
};

NativePreview::NativePreview(NativePreviewControl &control) : impl_(std::make_unique<Impl>(control))
{
#ifdef _WIN32
    if (control.supported) impl_->thread = std::thread([this] {
        // Size the swapchain in physical pixels on scaled/mixed-DPI monitors.
        SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        while (!impl_->stopping.load()) {
            update();
            MsgWaitForMultipleObjectsEx(0, nullptr, 100, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
        }
        impl_->close();
        impl_->active.store(false);
        impl_->control.state.store(0);
    });
#endif
}
NativePreview::~NativePreview()
{
#ifdef _WIN32
    impl_->stopping.store(true);
    if (impl_->thread.joinable()) impl_->thread.join();
#endif
}
bool NativePreview::active() const
{
    return impl_->active.load();
}
void NativePreview::update()
{
#ifdef _WIN32
    MSG message{};
    while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    auto &control = impl_->control;
    if (control.wanted() && !active()) {
        control.state.store(1);
        if (impl_->open()) { impl_->active.store(true); control.state.store(2); }
        else { control.requested.store(false); control.state.store(3); }
    } else if (!control.wanted() && active()) {
        impl_->close();
        impl_->active.store(false);
        control.requested.store(false);
        control.state.store(0);
    }
#endif
}

} // namespace webobs
