// Win32 visibility regression, not a graphics/pixel/presentation qualification.
// Each child receives the desktop job host's STARTF_USESHOWWINDOW/SW_HIDE policy
// in a fresh process, so its first ShowWindow call has not been consumed.
#include "../src/native_preview_window.hpp"

#include <iostream>
#include <iterator>
#include <string>

namespace {
int child(bool original_show)
{
    STARTUPINFOW startup{sizeof(startup)};
    GetStartupInfoW(&startup);
    if (!(startup.dwFlags & STARTF_USESHOWWINDOW) || startup.wShowWindow != SW_HIDE) return 10;
    WNDCLASSW type{};
    type.lpfnWndProc = DefWindowProcW;
    type.hInstance = GetModuleHandleW(nullptr);
    type.lpszClassName = L"WebOBS.NativePreviewVisibilityTest";
    if (!RegisterClassW(&type)) return 11;
    HWND window = CreateWindowExW(0, type.lpszClassName, L"Native preview visibility regression",
                                 WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 320, 180,
                                 nullptr, nullptr, type.hInstance, nullptr);
    if (!window) return 12;
    bool passed = false;
    if (original_show) {
        ShowWindow(window, SW_SHOW);
        passed = !IsWindowVisible(window); // Demonstrates the old launch interaction.
    } else {
        passed = webobs::detail::show_native_preview_window(window) && IsWindowVisible(window);
    }
    DestroyWindow(window);
    if (!passed) return 13;
    if (!original_show) {
        // A later user reopen must work as well, without changing startup info.
        window = CreateWindowExW(0, type.lpszClassName, L"Native preview reopened",
                                 WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 320, 180,
                                 nullptr, nullptr, type.hInstance, nullptr);
        if (!window) return 14;
        passed = webobs::detail::show_native_preview_window(window) && IsWindowVisible(window);
        DestroyWindow(window);
        if (!passed) return 15;
    }
    return 0;
}

bool run_child(const wchar_t *mode)
{
    wchar_t executable[32768]{};
    const DWORD length = GetModuleFileNameW(nullptr, executable, DWORD(std::size(executable)));
    if (!length || length >= std::size(executable)) return false;
    std::wstring command = L"\"" + std::wstring(executable, length) + L"\" " + mode;
    STARTUPINFOW startup{sizeof(startup)};
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_HIDE;
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(executable, command.data(), nullptr, nullptr, FALSE, CREATE_NEW_CONSOLE,
                        nullptr, nullptr, &startup, &process)) {
        std::cerr << "FAIL CreateProcess: " << GetLastError() << '\n';
        return false;
    }
    CloseHandle(process.hThread);
    const DWORD wait = WaitForSingleObject(process.hProcess, 10000);
    DWORD code = 0;
    const bool exited = wait == WAIT_OBJECT_0 && GetExitCodeProcess(process.hProcess, &code);
    if (!exited) {
        TerminateProcess(process.hProcess, 124); // Only this test's owned child.
        WaitForSingleObject(process.hProcess, INFINITE);
    }
    CloseHandle(process.hProcess);
    if (!exited || code != 0) {
        std::cerr << "FAIL visibility child: wait=" << wait << " exit=" << code << '\n';
        return false;
    }
    return true;
}
} // namespace

int wmain(int argc, wchar_t **argv)
{
    if (argc == 2 && std::wstring(argv[1]) == L"--original-show") return child(true);
    if (argc == 2 && std::wstring(argv[1]) == L"--requested-show") return child(false);
    if (argc != 1) return 2;
    if (!run_child(L"--original-show") || !run_child(L"--requested-show")) return 1;
    std::cout << "Hidden process startup policy is reproduced; explicit native Program show/reopen is visible.\n"
                 "Not a D3D11 Present or window-pixel qualification.\n";
    return 0;
}
