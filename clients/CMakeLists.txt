cmake_minimum_required(VERSION 3.28)
project(webobs-native VERSION 2.0.0 LANGUAGES CXX)

set(WEBOBS_PACKAGE_VERSION "2.0.0-dev.1" CACHE STRING "Native package SemVer")
if(NOT WEBOBS_PACKAGE_VERSION MATCHES "^[0-9]+\\.[0-9]+\\.[0-9]+([-.][0-9A-Za-z.-]+)?$")
    message(FATAL_ERROR "WEBOBS_PACKAGE_VERSION must be a bounded SemVer-like value")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)

option(WEBOBS_ENFORCE_LOCKED_DEPENDENCIES "Require v2 release dependency pins" ON)
if(WEBOBS_ENFORCE_LOCKED_DEPENDENCIES)
    find_package(Qt6 6.11.2 EXACT REQUIRED COMPONENTS Core Core5Compat Gui Network Qml Quick)
else()
    find_package(Qt6 6.4 REQUIRED COMPONENTS Core Core5Compat Gui Network Qml Quick)
endif()
find_package(PkgConfig REQUIRED)
if(WEBOBS_ENFORCE_LOCKED_DEPENDENCIES)
    pkg_check_modules(GSTREAMER REQUIRED IMPORTED_TARGET
        gstreamer-1.0=1.28.6
        gstreamer-video-1.0=1.28.6
        gstreamer-rtsp-1.0=1.28.6
        gstreamer-app-1.0=1.28.6)
    pkg_check_modules(SODIUM REQUIRED IMPORTED_TARGET libsodium=1.0.22)
else()
    message(WARNING "Dependency pins are disabled: this configuration is for compile diagnostics only")
    pkg_check_modules(GSTREAMER REQUIRED IMPORTED_TARGET
        gstreamer-1.0 gstreamer-video-1.0 gstreamer-rtsp-1.0 gstreamer-app-1.0)
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
    include/webobs/client/stream_session_model.hpp
    include/webobs/client/studio_workspace.hpp
    include/webobs/client/talk_capture.hpp
    include/webobs/client/topology_plan.hpp
    src/main.cpp
    src/client_controller.cpp
    src/grant_codec.cpp
    src/media_pipeline.cpp
    src/scene_model.cpp
    src/secure_store.cpp
    src/stream_session_model.cpp
    src/studio_workspace.cpp
    src/talk_capture.cpp
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
    Qt6::Core Qt6::Core5Compat Qt6::Gui Qt6::Network Qt6::Qml Qt6::Quick
    PkgConfig::GSTREAMER PkgConfig::SODIUM)
target_compile_definitions(webobs-native PRIVATE
    WEBOBS_CLIENT_VERSION="${WEBOBS_PACKAGE_VERSION}"
    WEBOBS_QT_VERSION="6.11.2"
    WEBOBS_GSTREAMER_VERSION="1.28.6"
    WEBOBS_SODIUM_VERSION="1.0.22"
    WEBOBS_LOCKED_RUNTIME=$<BOOL:${WEBOBS_ENFORCE_LOCKED_DEPENDENCIES}>)
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
install(FILES README.md dependencies.lock.json DESTINATION share/webobs-native)
install(FILES packaging/THIRD_PARTY_NOTICES.md DESTINATION share/webobs-native)
install(FILES ../LICENSE DESTINATION share/licenses/webobs-native)
install(FILES packaging/io.github.liaoyk001.WebObsNative.desktop DESTINATION share/applications)
install(FILES packaging/io.github.liaoyk001.WebObsNative.svg
        DESTINATION share/icons/hicolor/scalable/apps)

set(CPACK_PACKAGE_NAME "WebObs-Native")
set(CPACK_PACKAGE_VENDOR "Web Camera Monitor Wall contributors")
set(CPACK_PACKAGE_VERSION "${WEBOBS_PACKAGE_VERSION}")
set(CPACK_PACKAGE_FILE_NAME "webobs-native-${WEBOBS_PACKAGE_VERSION}-${CMAKE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}")
set(CPACK_PACKAGE_CHECKSUM SHA256)
set(CPACK_RESOURCE_FILE_LICENSE "${CMAKE_CURRENT_SOURCE_DIR}/../LICENSE")
set(CPACK_GENERATOR "ZIP" CACHE STRING "CPack generators")
include(CPack)

include(CTest)
if(BUILD_TESTING)
    find_package(Qt6 REQUIRED COMPONENTS Test)
    qt_add_executable(webobs-native-model-tests
        tests/client_model_tests.cpp
        include/webobs/client/media_pipeline.hpp
        include/webobs/client/scene_model.hpp
        include/webobs/client/stream_session_model.hpp
        include/webobs/client/studio_workspace.hpp
        src/media_pipeline.cpp
        src/scene_model.cpp
        src/stream_session_model.cpp)
    target_sources(webobs-native-model-tests PRIVATE src/studio_workspace.cpp)
    target_include_directories(webobs-native-model-tests PRIVATE include)
    target_link_libraries(webobs-native-model-tests PRIVATE
        Qt6::Core Qt6::Gui Qt6::Test PkgConfig::GSTREAMER)
    target_compile_options(webobs-native-model-tests PRIVATE
        $<$<CXX_COMPILER_ID:GNU,Clang>:-Wall;-Wextra;-Wpedantic>)
    add_test(NAME webobs-native-model-tests COMMAND webobs-native-model-tests)
endif()
