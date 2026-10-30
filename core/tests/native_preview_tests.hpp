#pragma once
#include "webobs/native_preview.hpp"

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
}
