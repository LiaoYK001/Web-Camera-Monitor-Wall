// Test-only native Unicode Shell Link reader. Never shipped in the product.
#include <windows.h>
#include <shobjidl.h>
#include <iostream>
#include <cwchar>
#include <memory>

template<class T> struct ComRelease { void operator()(T *p) const { if (p) p->Release(); } };
int wmain(int argc, wchar_t **argv)
{
	if (argc != 3 || FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) return 2;
	int result = 3;
	{
		IShellLinkW *raw_link = nullptr;
		if (SUCCEEDED(CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&raw_link)))) {
			std::unique_ptr<IShellLinkW, ComRelease<IShellLinkW>> link(raw_link);
			IPersistFile *raw_file = nullptr;
			if (SUCCEEDED(link->QueryInterface(IID_PPV_ARGS(&raw_file)))) {
				std::unique_ptr<IPersistFile, ComRelease<IPersistFile>> file(raw_file);
				wchar_t target[32768]{}, arguments[32768]{};
				if (SUCCEEDED(file->Load(argv[1], STGM_READ)) &&
				    SUCCEEDED(link->GetPath(target, 32768, nullptr, SLGP_RAWPATH)) &&
				    SUCCEEDED(link->GetArguments(arguments, 32768))) {
					wchar_t target_long[32768]{}, expected_long[32768]{};
					const DWORD target_count = GetLongPathNameW(target, target_long, 32768);
					const DWORD expected_count = GetLongPathNameW(argv[2], expected_long, 32768);
					const bool canonical_matches = target_count > 0 && target_count < 32768 &&
						expected_count > 0 && expected_count < 32768 && ::_wcsicmp(target_long, expected_long) == 0;
					const auto attributes = GetFileAttributesW(target);
					const bool exists = attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
					const auto length = std::wcslen(target), expected_length = std::wcslen(argv[2]);
					std::size_t mismatch = 0;
					while (mismatch < length && mismatch < expected_length && target[mismatch] == argv[2][mismatch]) ++mismatch;
					std::cout << "{\"nativeTargetExists\":" << (exists ? "true" : "false")
						<< ",\"nativeTargetMatches\":" << (::_wcsicmp(target, argv[2]) == 0 ? "true" : "false")
						<< ",\"canonicalTargetMatches\":" << (canonical_matches ? "true" : "false")
						<< ",\"argumentsEmpty\":" << (arguments[0] == L'\0' ? "true" : "false")
						<< ",\"targetLength\":" << length << ",\"expectedLength\":" << expected_length
						<< ",\"firstMismatchOffset\":" << mismatch
						<< ",\"firstMismatchActualCodeUnit\":" << (mismatch < length ? unsigned(target[mismatch]) : 0)
						<< ",\"firstMismatchExpectedCodeUnit\":" << (mismatch < expected_length ? unsigned(argv[2][mismatch]) : 0)
						<< ",\"ansiCodePage\":" << GetACP() << "}" << std::endl;
					result = 0;
				}
			}
		}
	}
	CoUninitialize();
	return result;
}
