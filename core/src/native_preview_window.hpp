#pragma once

#include <windows.h>

namespace webobs::detail {

// The desktop job host starts webobsd with STARTF_USESHOWWINDOW/SW_HIDE to
// suppress its console. Win32 applies that startup policy to the FIRST
// ShowWindow call, ignoring SW_SHOW. An authenticated, later request for this
// separate Program window must explicitly show it without inheriting that
// process-start policy. This checks visibility only, not pixels or Present.
inline bool show_native_preview_window(HWND window)
{
    return SetWindowPos(window, nullptr, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_SHOWWINDOW) &&
           IsWindowVisible(window);
}

} // namespace webobs::detail
