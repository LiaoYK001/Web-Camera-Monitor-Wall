#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>

namespace webobs {

// HTTP/IPC requests never touch HWNDs or graphics objects. The engine owns them.
// A short, authenticated desktop lease closes the picture after logout/crash.
struct NativePreviewControl {
    bool supported = false;
    std::atomic<bool> requested{false};
    std::atomic<std::int64_t> expires_at{0};
    std::atomic<int> state{0}; // 0 closed, 1 opening, 2 visible, 3 failed
    std::atomic<std::uint64_t> frames{0};

    static std::int64_t now_ms()
    {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
                   std::chrono::steady_clock::now().time_since_epoch()).count();
    }
    void open()
    {
        expires_at.store(now_ms() + 15000);
        requested.store(true);
    }
    void renew()
    {
        if (requested.load()) expires_at.store(now_ms() + 15000);
    }
    bool wanted() const { return supported && requested.load() && now_ms() < expires_at.load(); }
};

// Direct libobs/D3D11 Program display: no encoder, RTP, MediaMTX or browser decoder.
class NativePreview {
public:
    explicit NativePreview(NativePreviewControl &control);
    ~NativePreview();
    NativePreview(const NativePreview &) = delete;
    NativePreview &operator=(const NativePreview &) = delete;
    bool active() const;
private:
    void update(); // Dedicated Win32 UI thread; never blocked by RTSP/WHIP I/O.
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace webobs
