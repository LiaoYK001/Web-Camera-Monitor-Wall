cmake_minimum_required(VERSION 3.20)
project(webobs_native_control_auth_boundary LANGUAGES CXX)

# Standalone renderer-free security boundary; no root project/libobs/Qt discovery.
# Loopback fixtures own a disposable authority; no production service or media
# process is required to build/run these tests.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(WEBOBS_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
find_package(OpenSSL REQUIRED COMPONENTS Crypto)
if(WIN32)
    # The vcpkg config target selects the matching Release/Debug static CRT.
    find_package(unofficial-sqlite3 CONFIG REQUIRED)
    set(WEBOBS_SQLITE_TARGET unofficial::sqlite3::sqlite3)
else()
    find_package(SQLite3 REQUIRED)
    # CMake 4.3 renamed the imported target; retain compatibility with 3.20.
    if(TARGET SQLite3::SQLite3)
        set(WEBOBS_SQLITE_TARGET SQLite3::SQLite3)
    else()
        set(WEBOBS_SQLITE_TARGET SQLite::SQLite3)
    endif()
endif()
find_package(Threads REQUIRED)
find_package(CURL REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
if(WIN32)
    find_package(jansson CONFIG REQUIRED)
    set(WEBOBS_AUTH_JSON_TARGET jansson::jansson)
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(JANSSON REQUIRED IMPORTED_TARGET jansson)
    set(WEBOBS_AUTH_JSON_TARGET PkgConfig::JANSSON)
endif()

add_library(webobs-native-control-auth STATIC
    "${WEBOBS_ROOT}/core/src/native_control_auth.cpp"
    "${WEBOBS_ROOT}/core/src/authentication.cpp")
target_include_directories(webobs-native-control-auth PUBLIC "${WEBOBS_ROOT}/core/include")
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

add_library(webobs-native-cluster-authorization STATIC
    "${WEBOBS_ROOT}/core/src/native_cluster_authorization.cpp")
target_link_libraries(webobs-native-cluster-authorization PUBLIC
    webobs-native-control-auth CURL::libcurl ${WEBOBS_AUTH_JSON_TARGET})
add_executable(webobs-native-cluster-authorization-probe
    "${WEBOBS_ROOT}/core/tests/native_cluster_authorization_probe.cpp")
target_link_libraries(webobs-native-cluster-authorization-probe PRIVATE webobs-native-cluster-authorization)
if(MSVC)
    target_compile_options(webobs-native-cluster-authorization PRIVATE /W4 /permissive- /utf-8)
    target_compile_options(webobs-native-cluster-authorization-probe PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-native-cluster-authorization PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(webobs-native-cluster-authorization-probe PRIVATE -Wall -Wextra -Wpedantic)
endif()

enable_testing()
add_test(NAME native-cluster-authorization COMMAND "${Python3_EXECUTABLE}" -B
    "${WEBOBS_ROOT}/native-host/tests/test_native_cluster_authorization.py"
    --probe "$<TARGET_FILE:webobs-native-cluster-authorization-probe>")
set_tests_properties(native-cluster-authorization PROPERTIES TIMEOUT 90)
add_test(NAME native-control-auth COMMAND webobs-native-control-auth-tests)
set_tests_properties(native-control-auth PROPERTIES TIMEOUT 30)

# GNU/LLVM nm evidence: reject renderer/media entry points in the entire archive,
# including defined and undefined symbols. MSVC builds retain the compile/link
# dependency proof; Windows product/runtime qualification is a separate gate.
if(CMAKE_NM AND NOT MSVC)
    add_test(NAME native-control-no-media-symbols
        COMMAND "${CMAKE_NM}" -C "$<TARGET_FILE:webobs-native-control-auth>")
    add_test(NAME native-cluster-no-media-symbols
        COMMAND "${CMAKE_NM}" -C "$<TARGET_FILE:webobs-native-cluster-authorization>")
    set_tests_properties(native-cluster-no-media-symbols PROPERTIES
        TIMEOUT 30
        FAIL_REGULAR_EXPRESSION "obs_startup|obs_shutdown|obs_scene_|obs_source_|obs_frontend_|gst_init|QApplication|QGuiApplication")
    set_tests_properties(native-control-no-media-symbols PROPERTIES
        TIMEOUT 30
        FAIL_REGULAR_EXPRESSION "obs_startup|obs_shutdown|obs_scene_|obs_source_|obs_frontend_|gst_init|QApplication|QGuiApplication")
endif()
