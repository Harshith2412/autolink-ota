// Cryptographic primitives used by the OTA client. All operations delegate to
// OpenSSL; this module only provides RAII wrappers and encoding helpers.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace autolink::crypto {

using Bytes = std::vector<uint8_t>;

std::string sha256_hex(const Bytes& data);
std::string sha256_hex(const std::string& data);
// Streams the file in fixed-size chunks (bounded memory). Throws on I/O error.
std::string sha256_file_hex(const std::string& path);

// Verifies an Ed25519 signature over `message`. Returns false for any
// malformed input; never throws on attacker-controlled data.
bool ed25519_verify(const Bytes& public_key, const Bytes& signature, const std::string& message);

// Strict decoders: return false on any invalid character or length.
bool hex_decode(const std::string& hex, Bytes& out);
bool base64_decode(const std::string& b64, Bytes& out);

// Constant-time comparison (used for digest comparison).
bool constant_time_equal(const std::string& a, const std::string& b);

}  // namespace autolink::crypto
