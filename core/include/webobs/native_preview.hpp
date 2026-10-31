#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>

namespace webobs {

// A requested graphics-thread observation, not evidence of non-black pixels or
// successful Present. Never contains source names, URLs, paths or native handles.
struct NativePreviewDrawSample {
    bool available = false;
    bool video_ready = false;
    bool main_texture_ready = false;
    bool output_bound = false;
    bool output_active = false;
    bool output_showing = false;
    std::uint32_t base_width = 0;
    std::uint32_t base_height = 0;
    std::uint32_t display_width = 0;
    std::uint32_t display_height = 0;
    std::uint64_t frame = 0;
    std::int64_t sampled_at_ms = 0;
};

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

    // Requests coalesce: only an authenticated GET asks the next draw callback
    // to acquire a source reference. Normal frames do no source traversal/reads.
    void request_draw_sample() { draw_sample_requested_.store(true, std::memory_order_relaxed); }
    bool consume_draw_sample_request()
    {
        if (!draw_sample_requested_.load(std::memory_order_relaxed)) return false;
        return draw_sample_requested_.exchange(false, std::memory_order_relaxed);
    }
    NativePreviewDrawSample draw_sample() const
    {
        std::lock_guard lock(draw_sample_mutex_);
        return draw_sample_;
    }
    void publish_draw_sample(const NativePreviewDrawSample &sample)
    {
        std::lock_guard lock(draw_sample_mutex_);
        draw_sample_ = sample;
    }
    // Called before registering, or after removing, the draw callback. That
    // ordering prevents a previous window's callback from republishing stale data.
    void clear_draw_sample()
    {
        std::lock_guard lock(draw_sample_mutex_);
        draw_sample_ = {};
    }

private:
    std::atomic<bool> draw_sample_requested_{false};
    mutable std::mutex draw_sample_mutex_;
    NativePreviewDrawSample draw_sample_;
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
