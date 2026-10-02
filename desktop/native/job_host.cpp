#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <filesystem>
#include <string>
#include <thread>
#include <atomic>
#include <vector>

static BOOL WINAPI ignore_owned_console_signal(DWORD) { return TRUE; }

static std::wstring quote(const std::wstring& text) {
    std::wstring result = L"\""; size_t slash = 0;
    for (wchar_t character : text) {
        if (character == L'\\') { ++slash; continue; }
        result.append(character == L'"' ? slash * 2 + 1 : slash, L'\\'); slash = 0; result += character;
    }
    result.append(slash * 2, L'\\'); return result + L'"';
}
int wmain(int argc, wchar_t** argv) {
    wchar_t executable[32768]{};
    if (!GetModuleFileNameW(nullptr, executable, 32768)) return 125;
    const std::filesystem::path self(executable);
    std::vector<std::wstring> command;
    bool console_stop = false;
    if (self.stem() == L"webobs-job") {
        if (argc < 3 || (std::wstring(argv[1]) != L"--stdio" && std::wstring(argv[1]) != L"--console")) return 125;
        console_stop = std::wstring(argv[1]) == L"--console";
        for (int i = 2; i < argc; ++i) command.emplace_back(argv[i]);
    } else {
        const auto root = self.parent_path().parent_path();
        command = {(root / L"python/python.exe").wstring(), L"-B", (root / L"services/desktop-tools/tool_dispatch.py").wstring(), self.stem().wstring()};
        for (int i = 1; i < argc; ++i) command.emplace_back(argv[i]);
    }
    std::wstring line;
    for (const auto& arg : command) { if (!line.empty()) line += L' '; line += quote(arg); }
    HANDLE job = CreateJobObjectW(nullptr, nullptr);
    if (!job) return 125;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) { CloseHandle(job); return 125; }
    SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
    HANDLE input_read = nullptr, input_write = nullptr;
    if (!CreatePipe(&input_read, &input_write, &security, 0)) { CloseHandle(job); return 125; }
    SetHandleInformation(input_write, HANDLE_FLAG_INHERIT, 0);
    STARTUPINFOW startup{sizeof(startup)};
    startup.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW; startup.wShowWindow = SW_HIDE;
    startup.hStdInput = input_read; startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE); startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    PROCESS_INFORMATION child{};
    // Assign the suspended child before it can launch OBS helpers or FFmpeg.
    if (!CreateProcessW(command.front().c_str(), line.data(), nullptr, nullptr, TRUE,
                        CREATE_SUSPENDED | CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP, nullptr, nullptr, &startup, &child)) {
        CloseHandle(input_read); CloseHandle(input_write); CloseHandle(job); return 125;
    }
    CloseHandle(input_read);
    if (!AssignProcessToJobObject(job, child.hProcess)) {
        TerminateProcess(child.hProcess, 125); CloseHandle(child.hThread); CloseHandle(child.hProcess); CloseHandle(input_write); CloseHandle(job); return 125;
    }
    ResumeThread(child.hThread); CloseHandle(child.hThread);
    std::atomic<bool> requested{false};
    if (self.stem() == L"webobs-job") std::thread([&] {
        char buffer[64]{}; DWORD count = 0;
        // EOF also means the owner disappeared. Never accept command strings.
        ReadFile(GetStdHandle(STD_INPUT_HANDLE), buffer, sizeof(buffer), &count, nullptr);
        if (console_stop) {
            FreeConsole();
            if (AttachConsole(child.dwProcessId)) {
                SetConsoleCtrlHandler(ignore_owned_console_signal, TRUE);
                // CREATE_NEW_CONSOLE ignores CREATE_NEW_PROCESS_GROUP. This
                // console belongs only to our child and the attached job host.
                GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, 0);
            }
        } else { DWORD written = 0; WriteFile(input_write, "shutdown\n", 9, &written, nullptr); }
        requested.store(true);
    }).detach();
    while (WaitForSingleObject(child.hProcess, 100) == WAIT_TIMEOUT) {
        if (requested.load() && WaitForSingleObject(child.hProcess, 30000) == WAIT_TIMEOUT) {
            TerminateJobObject(job, 124); WaitForSingleObject(child.hProcess, INFINITE); break;
        }
    }
    DWORD code = 125; GetExitCodeProcess(child.hProcess, &code);
    // Process termination closes the job even on a forced Electron exit.
    CloseHandle(input_write); CloseHandle(child.hProcess); CloseHandle(job);
    ExitProcess(code); // A detached reader must never outlive its stack references.
}
