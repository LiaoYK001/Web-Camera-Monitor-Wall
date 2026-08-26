cmake_minimum_required(VERSION 3.28)

project(webobs VERSION 2.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(WEBOBS_BUILD_TESTS "Build the webobs unit tests" ON)
set(WEBOBS_OBS_SOURCE_DIR "${CMAKE_SOURCE_DIR}/obs/obs-studio" CACHE PATH "OBS Studio source directory")
set(WEBOBS_OBS_BUILD_DIR "${WEBOBS_OBS_SOURCE_DIR}/build_ubuntu" CACHE PATH "OBS Studio build directory")
set(WEBOBS_OBS_PREFIX "/opt/obs" CACHE PATH "Runtime OBS installation prefix")
set(WEBOBS_WEB_ROOT "/opt/webobs/ui" CACHE PATH "Installed WebOBS editor root")
set(WEBOBS_VERSION_OVERRIDE "${PROJECT_VERSION}-dev.0" CACHE STRING "Reported product version")
set(WEBOBS_MILESTONE_OVERRIDE "v2-M3-dev" CACHE STRING "Reported product milestone")
if(NOT WEBOBS_VERSION_OVERRIDE MATCHES "^[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.-]+)?$")
    message(FATAL_ERROR "WEBOBS_VERSION_OVERRIDE is not a safe SemVer value")
endif()
if(NOT WEBOBS_MILESTONE_OVERRIDE MATCHES "^v[0-9]+-M[0-9]+(-dev)?$")
    message(FATAL_ERROR "WEBOBS_MILESTONE_OVERRIDE is invalid")
endif()

find_package(PkgConfig REQUIRED)
find_package(Boost 1.83 REQUIRED)
find_package(CURL REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(SQLite3 REQUIRED)
find_package(Threads REQUIRED)
pkg_check_modules(JANSSON REQUIRED IMPORTED_TARGET jansson)

add_library(webobs-common
    core/src/authentication.cpp
    core/src/audit_event.cpp
    core/src/browser_security.cpp
    core/src/config.cpp
    core/src/redaction.cpp
    core/src/scene_document.cpp
    core/src/scene_mutation.cpp
    core/src/scene_store.cpp
    core/src/studio_document.cpp
    core/src/studio_store.cpp
    core/src/video_encoder.cpp
)
target_include_directories(webobs-common PUBLIC core/include)
target_link_libraries(webobs-common PUBLIC PkgConfig::JANSSON OpenSSL::Crypto SQLite::SQLite3)
target_compile_features(webobs-common PUBLIC cxx_std_20)
target_compile_options(webobs-common PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(webobs-common PUBLIC
    WEBOBS_VERSION="${WEBOBS_VERSION_OVERRIDE}"
    WEBOBS_MILESTONE="${WEBOBS_MILESTONE_OVERRIDE}"
)

set(_obs_library "${WEBOBS_OBS_BUILD_DIR}/libobs/libobs.so")
set(_obs_config_header "${WEBOBS_OBS_BUILD_DIR}/config/obsconfig.h")
if(NOT EXISTS "${_obs_library}")
    message(FATAL_ERROR "libobs build output not found: ${_obs_library}")
endif()
if(NOT EXISTS "${_obs_config_header}")
    message(FATAL_ERROR "Generated libobs header not found: ${_obs_config_header}")
endif()

add_library(webobs-libobs SHARED IMPORTED GLOBAL)
set_target_properties(webobs-libobs PROPERTIES
    IMPORTED_LOCATION "${_obs_library}"
    INTERFACE_INCLUDE_DIRECTORIES "${WEBOBS_OBS_SOURCE_DIR}/libobs;${WEBOBS_OBS_BUILD_DIR}/config"
)

add_executable(webobsd
    core/src/control_server.cpp
    core/src/main.cpp
    core/src/obs_engine.cpp
    core/src/obs_scene_runtime.cpp
    core/src/scene_controller.cpp
    core/src/studio_controller.cpp
)
target_link_libraries(webobsd PRIVATE webobs-common webobs-libobs Boost::headers CURL::libcurl Threads::Threads)
target_compile_options(webobsd PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(webobsd PRIVATE
    WEBOBS_OBS_PREFIX="${WEBOBS_OBS_PREFIX}"
    WEBOBS_WEB_ROOT="${WEBOBS_WEB_ROOT}"
    BOOST_ERROR_CODE_HEADER_ONLY
    BOOST_SYSTEM_NO_DEPRECATED
)
set_target_properties(webobsd PROPERTIES
    BUILD_RPATH "${WEBOBS_OBS_BUILD_DIR}/rundir/Release/lib"
    INSTALL_RPATH "$ORIGIN/../lib"
)
install(TARGETS webobsd RUNTIME DESTINATION bin)

add_executable(webobs-log-filter
    core/src/log_filter.cpp
    core/src/redaction.cpp
)
target_include_directories(webobs-log-filter PRIVATE core/include)
target_compile_features(webobs-log-filter PRIVATE cxx_std_20)
target_compile_options(webobs-log-filter PRIVATE -Wall -Wextra -Wpedantic)
install(TARGETS webobs-log-filter RUNTIME DESTINATION bin)

add_executable(webobs-scene-tool core/src/scene_tool.cpp)
target_link_libraries(webobs-scene-tool PRIVATE webobs-common)
target_compile_options(webobs-scene-tool PRIVATE -Wall -Wextra -Wpedantic)
install(TARGETS webobs-scene-tool RUNTIME DESTINATION bin)

if(WEBOBS_BUILD_TESTS)
    include(CTest)
    add_executable(webobs-unit-tests core/tests/common_tests.cpp)
    target_link_libraries(webobs-unit-tests PRIVATE webobs-common)
    target_compile_options(webobs-unit-tests PRIVATE -Wall -Wextra -Wpedantic)
    add_test(NAME webobs-unit-tests COMMAND webobs-unit-tests)
endif()
