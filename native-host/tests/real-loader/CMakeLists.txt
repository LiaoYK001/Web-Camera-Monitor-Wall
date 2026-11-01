cmake_minimum_required(VERSION 3.24)
project(native_legacy_real_loader_gate LANGUAGES CXX)

# Standalone test gate against the exported, pinned upstream SDK. No frontend,
# plugin discovery, installation, or product build dependency is introduced.
find_package(libobs 32.1.2 EXACT CONFIG REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_executable(native-legacy-loader-probe loader_probe.cpp)
target_compile_features(native-legacy-loader-probe PRIVATE cxx_std_17)
set_target_properties(native-legacy-loader-probe PROPERTIES CXX_EXTENSIONS OFF)
target_link_libraries(native-legacy-loader-probe PRIVATE OBS::libobs)
if(MSVC)
  target_compile_definitions(native-legacy-loader-probe PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
  target_compile_options(native-legacy-loader-probe PRIVATE /W4 /permissive- /utf-8 /EHsc)
else()
  target_compile_options(native-legacy-loader-probe PRIVATE -Wall -Wextra -Wpedantic)
endif()

enable_testing()
add_test(NAME native-legacy-real-loader
  COMMAND "${Python3_EXECUTABLE}" -B "${CMAKE_CURRENT_LIST_DIR}/../test_real_legacy_loader.py"
          --probe $<TARGET_FILE:native-legacy-loader-probe>)
set_tests_properties(native-legacy-real-loader PROPERTIES TIMEOUT 60 LABELS "no-media;no-gpu")
