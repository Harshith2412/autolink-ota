#include "autolink/crypto.hpp"

#include <fstream>
#include <memory>
#include <stdexcept>

#include "openssl_compat.h"

namespace autolink::crypto {
namespace {
struct MdCtxDeleter {
  void operator()(EVP_MD_CTX* p) const { EVP_MD_CTX_free(p); }
};
struct PkeyDeleter {
  void operator()(EVP_PKEY* p) const { EVP_PKEY_free(p); }
};
using MdCtxPtr = std::unique_ptr<EVP_MD_CTX, MdCtxDeleter>;
using PkeyPtr = std::unique_ptr<EVP_PKEY, PkeyDeleter>;

constexpr size_t kEd25519PublicKeyLen = 32;
constexpr size_t kEd25519SignatureLen = 64;
constexpr size_t kHashChunk = 64 * 1024;
constexpr unsigned kSha256Len = 32;

std::string to_hex(const unsigned char* d, unsigned len) {
  static const char* kDigits = "0123456789abcdef";
  std::string out;
  out.reserve(len * 2);
  for (unsigned i = 0; i < len; ++i) {
    out += kDigits[d[i] >> 4];
    out += kDigits[d[i] & 0xF];
  }
  return out;
}

class Sha256 {
 public:
  Sha256() : ctx_(EVP_MD_CTX_new()) {
    if (!ctx_ || EVP_DigestInit_ex(ctx_.get(), EVP_sha256(), nullptr) != 1)
      throw std::runtime_error("sha256 init failed");
  }
  void update(const void* d, size_t n) {
    if (EVP_DigestUpdate(ctx_.get(), d, n) != 1) throw std::runtime_error("sha256 update failed");
  }
  std::string final_hex() {
    unsigned char md[kSha256Len];
    unsigned len = 0;
    if (EVP_DigestFinal_ex(ctx_.get(), md, &len) != 1) throw std::runtime_error("sha256 final failed");
    return to_hex(md, len);
  }

 private:
  MdCtxPtr ctx_;
};
}  // namespace

std::string sha256_hex(const Bytes& data) {
  Sha256 h;
  h.update(data.data(), data.size());
  return h.final_hex();
}

std::string sha256_hex(const std::string& data) {
  Sha256 h;
  h.update(data.data(), data.size());
  return h.final_hex();
}

std::string sha256_file_hex(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("cannot open for hashing: " + path);
  Sha256 h;
  std::vector<char> buf(kHashChunk);
  while (in) {
    in.read(buf.data(), static_cast<std::streamsize>(buf.size()));
    if (in.gcount() > 0) h.update(buf.data(), static_cast<size_t>(in.gcount()));
  }
  if (in.bad()) throw std::runtime_error("read error while hashing: " + path);
  return h.final_hex();
}

bool ed25519_verify(const Bytes& public_key, const Bytes& signature, const std::string& message) {
  if (public_key.size() != kEd25519PublicKeyLen || signature.size() != kEd25519SignatureLen)
    return false;
  PkeyPtr key(EVP_PKEY_new_raw_public_key(EVP_PKEY_ED25519, nullptr, public_key.data(),
                                          public_key.size()));
  if (!key) return false;
  MdCtxPtr ctx(EVP_MD_CTX_new());
  if (!ctx) return false;
  // Ed25519 is a "one-shot" scheme in OpenSSL: digest type must be NULL.
  if (EVP_DigestVerifyInit(ctx.get(), nullptr, nullptr, nullptr, key.get()) != 1) return false;
  int rc = EVP_DigestVerify(ctx.get(), signature.data(), signature.size(),
                            reinterpret_cast<const unsigned char*>(message.data()), message.size());
  return rc == 1;
}

bool hex_decode(const std::string& hex, Bytes& out) {
  if (hex.size() % 2 != 0) return false;
  out.clear();
  auto nib = [](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  };
  for (size_t i = 0; i < hex.size(); i += 2) {
    int hi = nib(hex[i]), lo = nib(hex[i + 1]);
    if (hi < 0 || lo < 0) return false;
    out.push_back(static_cast<uint8_t>(hi << 4 | lo));
  }
  return true;
}

bool base64_decode(const std::string& in, Bytes& out) {
  auto val = [](char c) -> int {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    return -1;
  };
  if (in.size() % 4 != 0) return false;
  out.clear();
  for (size_t i = 0; i < in.size(); i += 4) {
    int v[4];
    int pad = 0;
    for (int j = 0; j < 4; ++j) {
      char c = in[i + j];
      if (c == '=') {
        if (i + 4 != in.size() || j < 2) return false;
        v[j] = 0;
        ++pad;
      } else {
        if (pad) return false;
        v[j] = val(c);
        if (v[j] < 0) return false;
      }
    }
    uint32_t n = (static_cast<uint32_t>(v[0]) << 18) | (static_cast<uint32_t>(v[1]) << 12) |
                 (static_cast<uint32_t>(v[2]) << 6) | static_cast<uint32_t>(v[3]);
    out.push_back(static_cast<uint8_t>(n >> 16));
    if (pad < 2) out.push_back(static_cast<uint8_t>(n >> 8));
    if (pad < 1) out.push_back(static_cast<uint8_t>(n));
  }
  return true;
}

bool constant_time_equal(const std::string& a, const std::string& b) {
  if (a.size() != b.size()) return false;
  unsigned char diff = 0;
  for (size_t i = 0; i < a.size(); ++i) diff |= static_cast<unsigned char>(a[i] ^ b[i]);
  return diff == 0;
}

}  // namespace autolink::crypto
