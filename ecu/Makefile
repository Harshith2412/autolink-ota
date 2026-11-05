# Offline-friendly build for the ECU simulator (the CMake build is the primary one).
CXX ?= g++
CXXFLAGS ?= -std=c++17 -O2 -g -Wall -Wextra -Wpedantic -Werror -Iinclude
BUILD := build-make
SRCS := src/json.cpp src/crypto.cpp src/update_state.cpp src/ecu_state.cpp src/manifest.cpp \
        src/ota_agent.cpp src/http_link.cpp
OBJS := $(SRCS:src/%.cpp=$(BUILD)/%.o)

# Link OpenSSL libcrypto; fall back to the runtime soname when no -dev package is installed.
CRYPTO_LIBS := $(shell pkg-config --libs libcrypto 2>/dev/null)
ifeq ($(strip $(CRYPTO_LIBS)),)
CRYPTO_LIBS := -l:libcrypto.so.3
endif

.PHONY: all test clean
all: $(BUILD)/autolink-ecu $(BUILD)/ecu_tests

$(BUILD)/%.o: src/%.cpp $(wildcard include/autolink/*.hpp) src/openssl_compat.h | $(BUILD)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(BUILD)/autolink-ecu: $(OBJS) $(BUILD)/main.o
	$(CXX) $^ -o $@ $(CRYPTO_LIBS)

$(BUILD)/ecu_tests: $(OBJS) tests/ecu_tests.cpp tests/test_framework.hpp
	$(CXX) $(CXXFLAGS) -DAUTOLINK_FORCE_MINI_TEST -DAUTOLINK_FIXTURE_DIR='"$(CURDIR)/tests/fixtures"' \
	  tests/ecu_tests.cpp $(OBJS) -o $@ $(CRYPTO_LIBS)

$(BUILD):
	mkdir -p $(BUILD)

test: $(BUILD)/ecu_tests
	./$(BUILD)/ecu_tests

clean:
	rm -rf $(BUILD)
