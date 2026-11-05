// Minimal JSON implementation for the ECU simulator.
// Scope: RFC 8259 objects/arrays/strings/numbers/bools/null, UTF-8 passthrough,
// \uXXXX escapes in the BMP. Bounded nesting depth to prevent stack exhaustion
// on hostile input. A production build would use a maintained library
// (e.g. nlohmann/json); this exists because the build sandbox was offline.
#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

namespace autolink::json {

class Value;
using Object = std::map<std::string, Value>;
using Array = std::vector<Value>;

class ParseError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

class Value {
 public:
  using Storage = std::variant<std::nullptr_t, bool, double, std::string,
                               std::shared_ptr<Array>, std::shared_ptr<Object>>;

  Value() : v_(nullptr) {}
  Value(std::nullptr_t) : v_(nullptr) {}
  Value(bool b) : v_(b) {}
  Value(int i) : v_(static_cast<double>(i)) {}
  Value(int64_t i) : v_(static_cast<double>(i)) {}
  Value(uint64_t i) : v_(static_cast<double>(i)) {}
  Value(double d) : v_(d) {}
  Value(const char* s) : v_(std::string(s)) {}
  Value(std::string s) : v_(std::move(s)) {}
  Value(Array a) : v_(std::make_shared<Array>(std::move(a))) {}
  Value(Object o) : v_(std::make_shared<Object>(std::move(o))) {}

  bool is_null() const { return std::holds_alternative<std::nullptr_t>(v_); }
  bool is_bool() const { return std::holds_alternative<bool>(v_); }
  bool is_number() const { return std::holds_alternative<double>(v_); }
  bool is_string() const { return std::holds_alternative<std::string>(v_); }
  bool is_array() const { return std::holds_alternative<std::shared_ptr<Array>>(v_); }
  bool is_object() const { return std::holds_alternative<std::shared_ptr<Object>>(v_); }

  bool as_bool() const { return get<bool>("bool"); }
  double as_number() const { return get<double>("number"); }
  int64_t as_int() const;
  const std::string& as_string() const { return get<std::string>("string"); }
  const Array& as_array() const { return *get<std::shared_ptr<Array>>("array"); }
  const Object& as_object() const { return *get<std::shared_ptr<Object>>("object"); }

  bool has(const std::string& key) const {
    return is_object() && as_object().count(key) > 0;
  }
  const Value& at(const std::string& key) const;
  // Typed accessors with explicit failure (no silent defaults for required fields).
  std::string str(const std::string& key) const { return at(key).as_string(); }
  int64_t integer(const std::string& key) const { return at(key).as_int(); }

  std::string dump() const;

 private:
  template <typename T>
  const T& get(const char* name) const {
    if (auto p = std::get_if<T>(&v_)) return *p;
    throw std::runtime_error(std::string("json: value is not a ") + name);
  }
  Storage v_;
};

Value parse(const std::string& text);

}  // namespace autolink::json
