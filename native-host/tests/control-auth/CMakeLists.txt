cmake_minimum_required(VERSION 3.20)
project(webobs_native_control_auth_boundary LANGUAGES CXX)

# Standalone renderer-free security boundary; no root project/libobs/Qt discovery.
# Loopback fixtures own a disposable authority; no production service or media
# process is required to build/run these tests.
set(CMAKE_CXX_STANDARD 20)
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
    "${WEBOBS_ROOT}/core/src/native_operation_auth.cpp"
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

add_executable(webobs-session-identity-tests "${WEBOBS_ROOT}/core/tests/session_identity_tests.cpp")
target_link_libraries(webobs-session-identity-tests PRIVATE webobs-native-control-auth)
if(MSVC)
    target_compile_options(webobs-session-identity-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-session-identity-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-native-operation-auth-tests "${WEBOBS_ROOT}/core/tests/native_operation_auth_tests.cpp")
target_link_libraries(webobs-native-operation-auth-tests PRIVATE webobs-native-control-auth)
if(MSVC)
    target_compile_options(webobs-native-operation-auth-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-native-operation-auth-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Live-view pipeline links the core auth boundary with the pure native-host
# pairing modules; the native-host sources stay OBS-, Qt- and I/O-free.
add_library(webobs-native-live-view-pipeline STATIC
    "${WEBOBS_ROOT}/native-host/src/live_view_pipeline.cpp"
    "${WEBOBS_ROOT}/native-host/src/wall_live_decision.cpp"
    "${WEBOBS_ROOT}/native-host/src/source_ownership.cpp")
target_include_directories(webobs-native-live-view-pipeline PUBLIC
    "${WEBOBS_ROOT}/core/include" "${WEBOBS_ROOT}/native-host/src")
target_link_libraries(webobs-native-live-view-pipeline PUBLIC webobs-native-control-auth)
if(MSVC)
    target_compile_options(webobs-native-live-view-pipeline PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-native-live-view-pipeline PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-live-view-pipeline-tests "${WEBOBS_ROOT}/native-host/tests/live_view_pipeline_test.cpp")
target_link_libraries(webobs-live-view-pipeline-tests PRIVATE webobs-native-live-view-pipeline)
if(MSVC)
    target_compile_options(webobs-live-view-pipeline-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-live-view-pipeline-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_library(webobs-native-wall-apply-authorization STATIC
    "${WEBOBS_ROOT}/native-host/src/wall_apply_authorization.cpp"
    "${WEBOBS_ROOT}/native-host/src/wall_apply_executor.cpp"
    "${WEBOBS_ROOT}/native-host/src/wall_apply_backup.cpp"
    "${WEBOBS_ROOT}/native-host/src/wall_apply_backup_executor.cpp"
    "${WEBOBS_ROOT}/native-host/src/wall_apply_flow.cpp"
    "${WEBOBS_ROOT}/native-host/src/native_ui_gate.cpp"
    "${WEBOBS_ROOT}/native-host/src/camera_catalog_binding.cpp"
    "${WEBOBS_ROOT}/native-host/src/wall_apply_plan.cpp"
    "${WEBOBS_ROOT}/native-host/src/source_ownership.cpp")
target_include_directories(webobs-native-wall-apply-authorization PUBLIC
    "${WEBOBS_ROOT}/core/include" "${WEBOBS_ROOT}/native-host/src")
target_link_libraries(webobs-native-wall-apply-authorization PUBLIC webobs-native-control-auth)
if(MSVC)
    target_compile_options(webobs-native-wall-apply-authorization PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-native-wall-apply-authorization PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-wall-apply-authorization-tests
    "${WEBOBS_ROOT}/native-host/tests/wall_apply_authorization_test.cpp")
target_link_libraries(webobs-wall-apply-authorization-tests PRIVATE webobs-native-wall-apply-authorization)
if(MSVC)
    target_compile_options(webobs-wall-apply-authorization-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-wall-apply-authorization-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-wall-apply-backup-executor-tests
    "${WEBOBS_ROOT}/native-host/tests/wall_apply_backup_executor_test.cpp")
target_link_libraries(webobs-wall-apply-backup-executor-tests PRIVATE webobs-native-wall-apply-authorization)
if(MSVC)
    target_compile_options(webobs-wall-apply-backup-executor-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-wall-apply-backup-executor-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-wall-apply-flow-tests
    "${WEBOBS_ROOT}/native-host/tests/wall_apply_flow_test.cpp")
target_link_libraries(webobs-wall-apply-flow-tests PRIVATE webobs-native-wall-apply-authorization)
if(MSVC)
    target_compile_options(webobs-wall-apply-flow-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-wall-apply-flow-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-startup-bootstrap-tests
    "${WEBOBS_ROOT}/native-host/tests/startup_bootstrap_test.cpp"
    "${WEBOBS_ROOT}/native-host/src/startup_bootstrap.cpp"
    "${WEBOBS_ROOT}/native-host/src/native_ui_gate.cpp")
target_include_directories(webobs-startup-bootstrap-tests PRIVATE "${WEBOBS_ROOT}/native-host/src")
if(MSVC)
    target_compile_options(webobs-startup-bootstrap-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-startup-bootstrap-tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_executable(webobs-native-ui-gate-tests
    "${WEBOBS_ROOT}/native-host/tests/native_ui_gate_test.cpp")
target_link_libraries(webobs-native-ui-gate-tests PRIVATE webobs-native-wall-apply-authorization)
if(MSVC)
    target_compile_options(webobs-native-ui-gate-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-native-ui-gate-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-camera-catalog-binding-tests
    "${WEBOBS_ROOT}/native-host/tests/camera_catalog_binding_test.cpp")
target_link_libraries(webobs-camera-catalog-binding-tests PRIVATE webobs-native-wall-apply-authorization)
if(MSVC)
    target_compile_options(webobs-camera-catalog-binding-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-camera-catalog-binding-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-wall-apply-backup-tests
    "${WEBOBS_ROOT}/native-host/tests/wall_apply_backup_test.cpp")
target_link_libraries(webobs-wall-apply-backup-tests PRIVATE webobs-native-wall-apply-authorization)
if(MSVC)
    target_compile_options(webobs-wall-apply-backup-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-wall-apply-backup-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(webobs-wall-apply-executor-tests
    "${WEBOBS_ROOT}/native-host/tests/wall_apply_executor_test.cpp")
target_link_libraries(webobs-wall-apply-executor-tests PRIVATE webobs-native-wall-apply-authorization)
if(MSVC)
    target_compile_options(webobs-wall-apply-executor-tests PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(webobs-wall-apply-executor-tests PRIVATE -Wall -Wextra -Wpedantic)
endif()

enable_testing()
add_test(NAME session-identity COMMAND webobs-session-identity-tests)
set_tests_properties(session-identity PROPERTIES TIMEOUT 30)
add_test(NAME native-account-identity COMMAND "${Python3_EXECUTABLE}" -B
    "${WEBOBS_ROOT}/native-host/tests/test_native_account_identity.py")
set_tests_properties(native-account-identity PROPERTIES TIMEOUT 30)
add_test(NAME native-cluster-authorization COMMAND "${Python3_EXECUTABLE}" -B
    "${WEBOBS_ROOT}/native-host/tests/test_native_cluster_authorization.py"
    --probe "$<TARGET_FILE:webobs-native-cluster-authorization-probe>")
set_tests_properties(native-cluster-authorization PROPERTIES TIMEOUT 90)
add_test(NAME native-control-auth COMMAND webobs-native-control-auth-tests)
set_tests_properties(native-control-auth PROPERTIES TIMEOUT 30)
add_test(NAME native-operation-auth COMMAND webobs-native-operation-auth-tests)
set_tests_properties(native-operation-auth PROPERTIES TIMEOUT 30)
add_test(NAME native-live-view-pipeline COMMAND webobs-live-view-pipeline-tests)
set_tests_properties(native-live-view-pipeline PROPERTIES TIMEOUT 30)
add_test(NAME native-wall-apply-authorization COMMAND webobs-wall-apply-authorization-tests)
set_tests_properties(native-wall-apply-authorization PROPERTIES TIMEOUT 30)
add_test(NAME native-wall-apply-executor COMMAND webobs-wall-apply-executor-tests)
set_tests_properties(native-wall-apply-executor PROPERTIES TIMEOUT 30)
add_test(NAME native-startup-bootstrap COMMAND webobs-startup-bootstrap-tests)
set_tests_properties(native-startup-bootstrap PROPERTIES TIMEOUT 30)
add_test(NAME native-ui-gate COMMAND webobs-native-ui-gate-tests)
set_tests_properties(native-ui-gate PROPERTIES TIMEOUT 30)
add_test(NAME native-wall-apply-flow COMMAND webobs-wall-apply-flow-tests)
set_tests_properties(native-wall-apply-flow PROPERTIES TIMEOUT 30)
add_test(NAME native-wall-apply-backup-executor COMMAND webobs-wall-apply-backup-executor-tests)
set_tests_properties(native-wall-apply-backup-executor PROPERTIES TIMEOUT 30)
add_test(NAME native-camera-catalog-binding COMMAND webobs-camera-catalog-binding-tests)
set_tests_properties(native-camera-catalog-binding PROPERTIES TIMEOUT 30)
add_test(NAME native-wall-apply-backup COMMAND webobs-wall-apply-backup-tests)
set_tests_properties(native-wall-apply-backup PROPERTIES TIMEOUT 30)

# GNU/LLVM nm evidence: reject renderer/media entry points in the entire archive,
# including defined and undefined symbols. MSVC builds retain the compile/link
# dependency proof; Windows product/runtime qualification is a separate gate.
if(CMAKE_NM AND NOT MSVC)
    add_test(NAME native-control-no-media-symbols
        COMMAND "${CMAKE_NM}" -C "$<TARGET_FILE:webobs-native-control-auth>")
    add_test(NAME native-cluster-no-media-symbols
        COMMAND "${CMAKE_NM}" -C "$<TARGET_FILE:webobs-native-cluster-authorization>")
    add_test(NAME native-live-view-no-media-symbols
        COMMAND "${CMAKE_NM}" -C "$<TARGET_FILE:webobs-native-live-view-pipeline>")
    add_test(NAME native-wall-apply-no-media-symbols
        COMMAND "${CMAKE_NM}" -C "$<TARGET_FILE:webobs-native-wall-apply-authorization>")
    set_tests_properties(native-cluster-no-media-symbols PROPERTIES
        TIMEOUT 30
        FAIL_REGULAR_EXPRESSION "obs_startup|obs_shutdown|obs_scene_|obs_source_|obs_frontend_|gst_init|QApplication|QGuiApplication")
    set_tests_properties(native-control-no-media-symbols PROPERTIES
        TIMEOUT 30
        FAIL_REGULAR_EXPRESSION "obs_startup|obs_shutdown|obs_scene_|obs_source_|obs_frontend_|gst_init|QApplication|QGuiApplication")
    set_tests_properties(native-live-view-no-media-symbols PROPERTIES
        TIMEOUT 30
        FAIL_REGULAR_EXPRESSION "obs_startup|obs_shutdown|obs_scene_|obs_source_|obs_frontend_|gst_init|QApplication|QGuiApplication")
    set_tests_properties(native-wall-apply-no-media-symbols PROPERTIES
        TIMEOUT 30
        FAIL_REGULAR_EXPRESSION "obs_startup|obs_shutdown|obs_scene_|obs_source_|obs_frontend_|gst_init|QApplication|QGuiApplication")
endif()
