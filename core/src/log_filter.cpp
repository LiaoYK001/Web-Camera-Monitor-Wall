#include "webobs/redaction.hpp"

#include <iostream>
#include <string>

int main()
{
    std::ios::sync_with_stdio(false);
    std::string line;
    while (std::getline(std::cin, line)) {
        std::cout << webobs::redact_rtsp_credentials(line) << '\n';
        std::cout.flush();
    }
    return std::cin.eof() ? 0 : 1;
}
