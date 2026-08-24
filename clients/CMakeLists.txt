cmake_minimum_required(VERSION 3.28)
project(webobs-native VERSION 2.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)

option(WEBOBS_ENFORCE_LOCKED_DEPENDENCIES "Require v2 release dependency pins" ON)
if(WEBOBS_ENFORCE_LOCKED_DEPENDENCIES)
    find_package(Qt6 6.11.2 EXACT REQUIRED COMPONENTS Core Gui Network Qml Quick)
else()
    find_package(Qt6 6.4 REQUIRED COMPONENTS Core Gui Network Qml Quick)
endif()
find_package(PkgConfig REQUIRED)
if(WEBOBS_ENFORCE_LOCKED_DEPENDENCIES)
    pkg_check_modules(GSTREAMER REQUIRED IMPORTED_TARGET
        gstreamer-1.0=1.28.6
        gstreamer-video-1.0=1.28.6
        gstreamer-rtsp-1.0=1.28.6)
    pkg_check_modules(SODIUM REQUIRED IMPORTED_TARGET libsodium=1.0.22)
else()
    message(WARNING "Dependency pins are disabled: this configuration is for compile diagnostics only")
    pkg_check_modules(GSTREAMER REQUIRED IMPORTED_TARGET
        gstreamer-1.0 gstreamer-video-1.0 gstreamer-rtsp-1.0)
    pkg_check_modules(SODIUM REQUIRED IMPORTED_TARGET libsodium)
endif()

if(UNIX AND NOT ANDROID)
    pkg_check_modules(LIBSECRET QUIET IMPORTED_TARGET libsecret-1)
endif()

qt_add_executable(webobs-native
    include/webobs/client/client_controller.hpp
    include/webobs/client/grant_codec.hpp
    include/webobs/client/media_pipeline.hpp
    include/webobs/client/scene_model.hpp
    include/webobs/client/secure_store.hpp
    include/webobs/client/topology_plan.hpp
    src/main.cpp
    src/client_controller.cpp
    src/grant_codec.cpp
    src/media_pipeline.cpp
    src/scene_model.cpp
    src/secure_store.cpp
    src/topology_plan.cpp
)
qt_add_qml_module(webobs-native
    URI WebObs.Native
    VERSION 2.0
    QML_FILES
        qml/Main.qml
        qml/MonitorTile.qml
        qml/StudioCanvas.qml
)
target_include_directories(webobs-native PRIVATE include)
target_link_libraries(webobs-native PRIVATE
    Qt6::Core Qt6::Gui Qt6::Network Qt6::Qml Qt6::Quick
    PkgConfig::GSTREAMER PkgConfig::SODIUM)
target_compile_definitions(webobs-native PRIVATE
    WEBOBS_CLIENT_VERSION="2.0.0-dev.1"
    WEBOBS_QT_VERSION="6.11.2"
    WEBOBS_GSTREAMER_VERSION="1.28.6"
    WEBOBS_SODIUM_VERSION="1.0.22")
target_compile_options(webobs-native PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang>:-Wall;-Wextra;-Wpedantic>)

if(WIN32)
    target_link_libraries(webobs-native PRIVATE crypt32)
    target_compile_definitions(webobs-native PRIVATE WEBOBS_SECURE_STORE_DPAPI=1)
elseif(ANDROID)
    target_compile_definitions(webobs-native PRIVATE WEBOBS_SECURE_STORE_ANDROID=1)
    set_property(TARGET webobs-native APPEND PROPERTY QT_ANDROID_PACKAGE_SOURCE_DIR
        "${CMAKE_CURRENT_SOURCE_DIR}/android")
elseif(LIBSECRET_FOUND)
    target_link_libraries(webobs-native PRIVATE PkgConfig::LIBSECRET)
    target_compile_definitions(webobs-native PRIVATE WEBOBS_SECURE_STORE_LIBSECRET=1)
else()
    message(WARNING "Secret Service is unavailable: only non-persistent temporary sessions will be allowed")
endif()

install(TARGETS webobs-native
    BUNDLE DESTINATION .
    RUNTIME DESTINATION bin)
