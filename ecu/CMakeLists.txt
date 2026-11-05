cmake_minimum_required(VERSION 3.20)
project(autolink_ecu LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

find_package(OpenSSL 3.0 REQUIRED COMPONENTS Crypto)

add_library(autolink_core
  src/json.cpp src/crypto.cpp src/update_state.cpp src/ecu_state.cpp
  src/manifest.cpp src/ota_agent.cpp src/http_link.cpp)
target_include_directories(autolink_core PUBLIC include)
target_link_libraries(autolink_core PUBLIC OpenSSL::Crypto)
target_compile_options(autolink_core PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(autolink-ecu src/main.cpp)
target_link_libraries(autolink-ecu PRIVATE autolink_core)

option(AUTOLINK_BUILD_TESTS "Build unit tests" ON)
if(AUTOLINK_BUILD_TESTS)
  enable_testing()
  include(FetchContent)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
  set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)
  add_executable(ecu_tests tests/ecu_tests.cpp)
  target_compile_definitions(ecu_tests PRIVATE AUTOLINK_FIXTURE_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures")
  target_link_libraries(ecu_tests PRIVATE autolink_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(ecu_tests)
endif()
