cmake_minimum_required(VERSION 3.20)
project(webobs_native_control_auth_boundary LANGUAGES CXX)

# Standalone renderer-free security boundary; no root project/libobs/Qt discovery,
# transport, account service or media process is required to build/run this test.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(WEBOBS_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
find_package(OpenSSL REQUIRED COMPONENTS Crypto)
find_package(SQLite3 REQUIRED)
find_package(Threads REQUIRED)

add_library(webobs-native-control-auth STATIC
    "${WEBOBS_ROOT}/core/src/native_control_auth.cpp"
    "${WEBOBS_ROOT}/core/src/authentication.cpp")
target_include_directories(webobs-native-control-auth PUBLIC "${WEBOBS_ROOT}/core/include")
# CMake 4.3 renamed the imported target; retain compatibility with 3.20.
if(TARGET SQLite3::SQLite3)
    set(WEBOBS_SQLITE_TARGET SQLite3::SQLite3)
else()
    set(WEBOBS_SQLITE_TARGET SQLite::SQLite3)
endif()
target_link_libraries(webobs-native-control-auth PUBLIC OpenSSL::Crypto ${WEBOBS_SQLITE_TARGET} Threads::Threads)
if(MSVC)
    target_compile_options(webobs-native-control-auth PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-native-control-auth PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-native-control-auth-tests
    "${WEBOBS_ROOT}/core/tests/native_control_auth_tests.cpp")
target_link_libraries(webobs-native-control-auth-tests PRIVATE webobs-native-control-auth)
if(MSVC)
    target_compile_options(webobs-native-control-auth-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-native-control-auth-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

enable_testing()
add_test(NAME native-control-auth COMMAND webobs-native-control-auth-tests)
set_tests_properties(native-control-auth PROPERTIES TIMEOUT 30)

# GNU/LLVM nm evidence: reject renderer/media entry points in the entire archive,
# including defined and undefined symbols. MSVC builds retain the compile/link
# dependency proof; Windows product/runtime qualification is a separate gate.
if(CMAKE_NM AND NOT MSVC)
    add_test(NAME native-control-no-media-symbols
        COMMAND "${CMAKE_NM}" -C "$<TARGET_FILE:webobs-native-control-auth>")
    set_tests_properties(native-control-no-media-symbols PROPERTIES
        TIMEOUT 30
        FAIL_REGULAR_EXPRESSION "obs_startup|obs_shutdown|obs_scene_|obs_source_|obs_frontend_|gst_init|QApplication|QGuiApplication")
endif()
