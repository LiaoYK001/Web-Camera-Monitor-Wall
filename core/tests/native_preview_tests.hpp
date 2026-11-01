#pragma once
#include "webobs/native_preview.hpp"
#include <thread>

template<class Expect> void native_preview_tests(Expect expect)
{
    webobs::NativePreviewControl control;
    control.open();
    expect(!control.wanted(), "an unsupported host must not open a native window");
    control.supported = true;
    expect(control.wanted(), "an authenticated open grants a short native preview lease");
    control.expires_at.store(webobs::NativePreviewControl::now_ms() - 1);
    expect(!control.wanted(), "a lost desktop heartbeat must expire the native picture");
    control.renew();
    expect(control.wanted(), "an authenticated heartbeat renews the current window");
    control.requested.store(false);
    control.renew();
    expect(!control.wanted(), "a status read must not reopen a user-closed window");

    expect(!control.draw_sample().available, "an unopened window has no graphics sample");
    expect(!control.consume_draw_sample_request(), "ordinary frames must not request source inspection");
    control.request_draw_sample();
    control.request_draw_sample();
    expect(control.consume_draw_sample_request(), "authenticated diagnostic requests trigger a sample");
    expect(!control.consume_draw_sample_request(), "diagnostic requests coalesce into one graphics sample");
    expect(!control.wanted(), "requesting diagnostics must not reopen a user-closed window");

    webobs::NativePreviewDrawSample sample;
    sample.available = true;
    sample.video_ready = true;
    sample.main_texture_ready = true;
    sample.output_bound = true;
    sample.output_active = true;
    sample.output_showing = true;
    sample.base_width = 1920;
    sample.base_height = 1080;
    sample.display_width = 1280;
    sample.display_height = 720;
    sample.frame = 7;
    sample.sampled_at_ms = 1234;
    control.publish_draw_sample(sample);
    const auto observed = control.draw_sample();
    expect(observed.available && observed.video_ready && observed.main_texture_ready && observed.output_bound &&
           observed.output_active && observed.output_showing && observed.base_width == 1920 &&
           observed.base_height == 1080 && observed.display_width == 1280 && observed.display_height == 720 &&
           observed.frame == 7 && observed.sampled_at_ms == 1234,
           "published graphics observations retain all fields coherently");
    control.clear_draw_sample();
    expect(!control.draw_sample().available && control.draw_sample().frame == 0,
           "closing or reopening a window invalidates the previous draw sample");

    std::atomic<bool> coherent{true};
    std::thread writer([&] {
        for (std::uint64_t index = 1; index <= 2000; ++index) {
            webobs::NativePreviewDrawSample next;
            next.available = true;
            next.frame = index;
            next.display_width = static_cast<std::uint32_t>(index);
            next.sampled_at_ms = static_cast<std::int64_t>(index);
            control.publish_draw_sample(next);
        }
    });
    for (int index = 0; index < 2000; ++index) {
        const auto next = control.draw_sample();
        if (next.available && (next.frame != next.display_width ||
                               next.frame != static_cast<std::uint64_t>(next.sampled_at_ms)))
            coherent.store(false);
    }
    writer.join();
    expect(coherent.load(), "concurrent HTTP/graphics readers must never see a torn snapshot");
}
