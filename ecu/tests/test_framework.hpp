// Uses GoogleTest when available (CMake build fetches/links it). Otherwise falls
// back to a tiny harness implementing the subset of the GoogleTest API these
// tests use, so the suite also runs in offline environments (the Makefile path).
#pragma once

#if __has_include(<gtest/gtest.h>) && !defined(AUTOLINK_FORCE_MINI_TEST)
#include <gtest/gtest.h>
#define AUTOLINK_USING_GTEST 1
#else
#define AUTOLINK_USING_GTEST 0
#include <functional>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace minitest {
struct Case {
  std::string name;
  std::function<void()> fn;
};
inline std::vector<Case>& registry() {
  static std::vector<Case> r;
  return r;
}
inline int& failures() {
  static int f = 0;
  return f;
}
struct Registrar {
  Registrar(const char* n, std::function<void()> f) { registry().push_back({n, std::move(f)}); }
};
struct FatalFailure {};
inline void report(const char* file, int line, const std::string& msg) {
  std::cerr << file << ":" << line << ": Failure: " << msg << "\n";
  ++failures();
}
inline int run_all() {
  int failed_cases = 0;
  for (auto& c : registry()) {
    int before = failures();
    try {
      c.fn();
    } catch (const FatalFailure&) {
    } catch (const std::exception& e) {
      report(c.name.c_str(), 0, std::string("uncaught exception: ") + e.what());
    }
    bool ok = failures() == before;
    if (!ok) ++failed_cases;
    std::cout << (ok ? "[       OK ] " : "[  FAILED  ] ") << c.name << "\n";
  }
  std::cout << "[==========] " << registry().size() << " tests, " << failed_cases << " failed\n";
  return failed_cases == 0 ? 0 : 1;
}
}  // namespace minitest

#define TEST(suite, name)                                                         \
  static void suite##_##name##_impl();                                            \
  static minitest::Registrar suite##_##name##_reg(#suite "." #name, suite##_##name##_impl); \
  static void suite##_##name##_impl()

#define MT_CHECK(cond, msg, fatal)                                  \
  do {                                                              \
    if (!(cond)) {                                                  \
      std::ostringstream mt_os;                                     \
      mt_os << msg;                                                 \
      minitest::report(__FILE__, __LINE__, mt_os.str());            \
      if (fatal) throw minitest::FatalFailure{};                    \
    }                                                               \
  } while (0)

#define EXPECT_TRUE(c) MT_CHECK((c), "expected true: " #c, false)
#define EXPECT_FALSE(c) MT_CHECK(!(c), "expected false: " #c, false)
#define ASSERT_TRUE(c) MT_CHECK((c), "expected true: " #c, true)
#define ASSERT_FALSE(c) MT_CHECK(!(c), "expected false: " #c, true)
#define EXPECT_EQ(a, b) MT_CHECK((a) == (b), "expected " #a " == " #b " (got " << (a) << " vs " << (b) << ")", false)
#define ASSERT_EQ(a, b) MT_CHECK((a) == (b), "expected " #a " == " #b " (got " << (a) << " vs " << (b) << ")", true)
#define EXPECT_NE(a, b) MT_CHECK((a) != (b), "expected " #a " != " #b, false)
#define EXPECT_GT(a, b) MT_CHECK((a) > (b), "expected " #a " > " #b " (got " << (a) << " vs " << (b) << ")", false)
#define EXPECT_THROW(stmt, ex)                                            \
  do {                                                                    \
    bool mt_thrown = false;                                               \
    try {                                                                 \
      stmt;                                                               \
    } catch (const ex&) {                                                 \
      mt_thrown = true;                                                   \
    }                                                                     \
    MT_CHECK(mt_thrown, "expected exception " #ex " from " #stmt, false); \
  } while (0)
#define EXPECT_NO_THROW(stmt)                                                    \
  do {                                                                           \
    try {                                                                        \
      stmt;                                                                      \
    } catch (const std::exception& mt_e) {                                       \
      MT_CHECK(false, "unexpected exception from " #stmt ": " << mt_e.what(), false); \
    }                                                                            \
  } while (0)
#endif
