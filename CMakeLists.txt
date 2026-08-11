cmake_minimum_required(VERSION 3.28)

project(webobs VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(WEBOBS_BUILD_TESTS "Build the webobs unit tests" ON)
set(WEBOBS_OBS_SOURCE_DIR "${CMAKE_SOURCE_DIR}/obs/obs-studio" CACHE PATH "OBS Studio source directory")
set(WEBOBS_OBS_BUILD_DIR "${WEBOBS_OBS_SOURCE_DIR}/build_ubuntu" CACHE PATH "OBS Studio build directory")
set(WEBOBS_OBS_PREFIX "/opt/obs" CACHE PATH "Runtime OBS installation prefix")

find_package(PkgConfig REQUIRED)
pkg_check_modules(JANSSON REQUIRED IMPORTED_TARGET jansson)

add_library(webobs-common
    core/src/config.cpp
    core/src/redaction.cpp
    core/src/scene_document.cpp
    core/src/scene_store.cpp
)
target_include_directories(webobs-common PUBLIC core/include)
target_link_libraries(webobs-common PUBLIC PkgConfig::JANSSON)
target_compile_features(webobs-common PUBLIC cxx_std_20)
target_compile_options(webobs-common PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(webobs-common PUBLIC WEBOBS_VERSION="${PROJECT_VERSION}")

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
    core/src/main.cpp
    core/src/obs_engine.cpp
)
target_link_libraries(webobsd PRIVATE webobs-common webobs-libobs)
target_compile_options(webobsd PRIVATE -Wall -Wextra -Wpedantic)
target_compile_definitions(webobsd PRIVATE WEBOBS_OBS_PREFIX="${WEBOBS_OBS_PREFIX}")
set_target_properties(webobsd PROPERTIES
    BUILD_RPATH "${WEBOBS_OBS_BUILD_DIR}/rundir/Release/lib"
    INSTALL_RPATH "$ORIGIN/../lib"
)
install(TARGETS webobsd RUNTIME DESTINATION bin)

if(WEBOBS_BUILD_TESTS)
    include(CTest)
    add_executable(webobs-unit-tests core/tests/common_tests.cpp)
    target_link_libraries(webobs-unit-tests PRIVATE webobs-common)
    target_compile_options(webobs-unit-tests PRIVATE -Wall -Wextra -Wpedantic)
    add_test(NAME webobs-unit-tests COMMAND webobs-unit-tests)
endif()
