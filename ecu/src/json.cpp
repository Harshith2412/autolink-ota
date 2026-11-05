#include "autolink/json.hpp"

#include <cmath>
#include <cstdio>
#include <sstream>

namespace autolink::json {

namespace {
constexpr int kMaxDepth = 32;

class Parser {
 public:
  explicit Parser(const std::string& s) : s_(s) {}

  Value parse_document() {
    Value v = parse_value(0);
    skip_ws();
    if (pos_ != s_.size()) fail("trailing characters");
    return v;
  }

 private:
  [[noreturn]] void fail(const std::string& why) const {
    throw ParseError("json parse error at offset " + std::to_string(pos_) + ": " + why);
  }
  void skip_ws() {
    while (pos_ < s_.size() &&
           (s_[pos_] == ' ' || s_[pos_] == '\n' || s_[pos_] == '\r' || s_[pos_] == '\t'))
      ++pos_;
  }
  char peek() {
    skip_ws();
    if (pos_ >= s_.size()) fail("unexpected end of input");
    return s_[pos_];
  }
  void expect(char c) {
    if (peek() != c) fail(std::string("expected '") + c + "'");
    ++pos_;
  }
  bool consume_literal(const char* lit) {
    std::string l(lit);
    if (s_.compare(pos_, l.size(), l) == 0) {
      pos_ += l.size();
      return true;
    }
    return false;
  }

  Value parse_value(int depth) {
    if (depth > kMaxDepth) fail("nesting too deep");
    char c = peek();
    if (c == '{') return parse_object(depth);
    if (c == '[') return parse_array(depth);
    if (c == '"') return Value(parse_string());
    if (consume_literal("true")) return Value(true);
    if (consume_literal("false")) return Value(false);
    if (consume_literal("null")) return Value(nullptr);
    return parse_number();
  }

  Value parse_object(int depth) {
    expect('{');
    Object obj;
    if (peek() == '}') {
      ++pos_;
      return Value(std::move(obj));
    }
    while (true) {
      if (peek() != '"') fail("expected object key");
      std::string key = parse_string();
      expect(':');
      obj[key] = parse_value(depth + 1);
      char c = peek();
      ++pos_;
      if (c == '}') break;
      if (c != ',') fail("expected ',' or '}'");
    }
    return Value(std::move(obj));
  }

  Value parse_array(int depth) {
    expect('[');
    Array arr;
    if (peek() == ']') {
      ++pos_;
      return Value(std::move(arr));
    }
    while (true) {
      arr.push_back(parse_value(depth + 1));
      char c = peek();
      ++pos_;
      if (c == ']') break;
      if (c != ',') fail("expected ',' or ']'");
    }
    return Value(std::move(arr));
  }

  static void append_utf8(std::string& out, unsigned cp) {
    if (cp < 0x80) {
      out += static_cast<char>(cp);
    } else if (cp < 0x800) {
      out += static_cast<char>(0xC0 | (cp >> 6));
      out += static_cast<char>(0x80 | (cp & 0x3F));
    } else {
      out += static_cast<char>(0xE0 | (cp >> 12));
      out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
      out += static_cast<char>(0x80 | (cp & 0x3F));
    }
  }

  std::string parse_string() {
    expect('"');
    std::string out;
    while (true) {
      if (pos_ >= s_.size()) fail("unterminated string");
      char c = s_[pos_++];
      if (c == '"') break;
      if (static_cast<unsigned char>(c) < 0x20) fail("control character in string");
      if (c != '\\') {
        out += c;
        continue;
      }
      if (pos_ >= s_.size()) fail("bad escape");
      char e = s_[pos_++];
      switch (e) {
        case '"': out += '"'; break;
        case '\\': out += '\\'; break;
        case '/': out += '/'; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case 'n': out += '\n'; break;
        case 'r': out += '\r'; break;
        case 't': out += '\t'; break;
        case 'u': {
          if (pos_ + 4 > s_.size()) fail("bad \\u escape");
          unsigned cp = std::stoul(s_.substr(pos_, 4), nullptr, 16);
          pos_ += 4;
          append_utf8(out, cp);
          break;
        }
        default: fail("unknown escape");
      }
    }
    return out;
  }

  Value parse_number() {
    size_t start = pos_;
    if (pos_ < s_.size() && (s_[pos_] == '-' || s_[pos_] == '+')) ++pos_;
    while (pos_ < s_.size() && (isdigit(static_cast<unsigned char>(s_[pos_])) || s_[pos_] == '.' ||
                                s_[pos_] == 'e' || s_[pos_] == 'E' || s_[pos_] == '-' ||
                                s_[pos_] == '+'))
      ++pos_;
    if (start == pos_) fail("unexpected character");
    try {
      size_t used = 0;
      std::string tok = s_.substr(start, pos_ - start);
      double d = std::stod(tok, &used);
      if (used != tok.size() || !std::isfinite(d)) fail("invalid number");
      return Value(d);
    } catch (const std::logic_error&) {
      fail("invalid number");
    }
  }

  const std::string& s_;
  size_t pos_ = 0;
};

void escape_into(std::ostringstream& os, const std::string& s) {
  os << '"';
  for (unsigned char c : s) {
    switch (c) {
      case '"': os << "\\\""; break;
      case '\\': os << "\\\\"; break;
      case '\n': os << "\\n"; break;
      case '\r': os << "\\r"; break;
      case '\t': os << "\\t"; break;
      default:
        if (c < 0x20) {
          char buf[8];
          std::snprintf(buf, sizeof buf, "\\u%04x", c);
          os << buf;
        } else {
          os << c;
        }
    }
  }
  os << '"';
}

void dump_into(std::ostringstream& os, const Value& v) {
  if (v.is_null()) {
    os << "null";
  } else if (v.is_bool()) {
    os << (v.as_bool() ? "true" : "false");
  } else if (v.is_number()) {
    double d = v.as_number();
    if (std::floor(d) == d && std::fabs(d) < 9.007199254740992e15) {
      os << static_cast<int64_t>(d);
    } else {
      os.precision(17);
      os << d;
    }
  } else if (v.is_string()) {
    escape_into(os, v.as_string());
  } else if (v.is_array()) {
    os << '[';
    bool first = true;
    for (const auto& e : v.as_array()) {
      if (!first) os << ',';
      first = false;
      dump_into(os, e);
    }
    os << ']';
  } else {
    os << '{';
    bool first = true;
    for (const auto& [k, e] : v.as_object()) {
      if (!first) os << ',';
      first = false;
      escape_into(os, k);
      os << ':';
      dump_into(os, e);
    }
    os << '}';
  }
}
}  // namespace

int64_t Value::as_int() const {
  double d = as_number();
  if (std::floor(d) != d) throw std::runtime_error("json: number is not an integer");
  return static_cast<int64_t>(d);
}

const Value& Value::at(const std::string& key) const {
  const auto& o = as_object();
  auto it = o.find(key);
  if (it == o.end()) throw std::runtime_error("json: missing key '" + key + "'");
  return it->second;
}

std::string Value::dump() const {
  std::ostringstream os;
  dump_into(os, *this);
  return os.str();
}

Value parse(const std::string& text) { return Parser(text).parse_document(); }

}  // namespace autolink::json
