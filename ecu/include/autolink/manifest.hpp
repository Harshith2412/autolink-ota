// Firmware manifest model and the verification policy the ECU enforces before
// any byte is staged (REQ-SEC-001..008).
#pragma once

#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>

#include "autolink/crypto.hpp"
#include "autolink/json.hpp"

namespace autolink {

constexpr int64_t kMaxFirmwareBytes = 16 * 1024 * 1024;  // REQ-SEC-007

struct SemVer {
  int64_t major = 0, minor = 0, patch = 0;
  static std::optional<SemVer> parse(const std::string& s);
  int compare(const SemVer& o) const;
};

struct FirmwareManifest {
  std::string firmware_id;
  std::string version;
  std::string hardware_id;
  std::string sha256;
  int64_t size = 0;
  int64_t security_counter = 0;
  std::string min_current_version;  // compatibility: ECU must already run >= this
  std::string key_id;
  std::string signature_b64;
  std::string release_notes;
  bool simulate_unhealthy = false;  // simulation hook, covered by the signature

  static FirmwareManifest from_json(const json::Value& v);
  // Canonical byte string the signature covers. Field order is fixed and every
  // field is length-prefixed, so no two manifests share a payload.
  std::string signing_payload() const;
};

enum class VerifyError {
  NONE,
  MALFORMED,
  UNKNOWN_KEY,
  REVOKED_KEY,
  BAD_SIGNATURE,
  WRONG_HARDWARE,
  ROLLBACK,
  INCOMPATIBLE_VERSION,
  TOO_LARGE,
  DIGEST_MISMATCH,
  SIZE_MISMATCH,
};
const char* to_string(VerifyError e);

struct VerifyResult {
  VerifyError error = VerifyError::NONE;
  std::string detail;
  bool ok() const { return error == VerifyError::NONE; }
};

class TrustStore {
 public:
  void add_key(const std::string& key_id, const crypto::Bytes& public_key);
  void revoke(const std::string& key_id) { revoked_.insert(key_id); }
  // Loads JSON: {"keys":[{"key_id":..,"public_key_b64":..}],"revoked":[..]}
  static TrustStore from_json(const json::Value& v);
  const crypto::Bytes* find(const std::string& key_id) const;
  bool is_revoked(const std::string& key_id) const { return revoked_.count(key_id) > 0; }

 private:
  std::map<std::string, crypto::Bytes> keys_;
  std::set<std::string> revoked_;
};

struct EcuIdentity {
  std::string hardware_id;
  std::string current_version;
  int64_t min_security_counter = 0;
};

// Authenticity + policy checks on the manifest (before download).
VerifyResult verify_manifest(const FirmwareManifest& m, const TrustStore& trust,
                             const EcuIdentity& ecu);
// Integrity check of the downloaded image against the (already verified) manifest.
VerifyResult verify_image(const FirmwareManifest& m, const std::string& image_path);

bool is_safe_identifier(const std::string& s);

}  // namespace autolink
