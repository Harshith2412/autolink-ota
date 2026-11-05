#include "autolink/manifest.hpp"

#include <sys/stat.h>

#include <regex>
#include <sstream>
#include <stdexcept>

namespace autolink {

std::optional<SemVer> SemVer::parse(const std::string& s) {
  static const std::regex re(R"(^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$)");
  std::smatch m;
  if (!std::regex_match(s, m, re)) return std::nullopt;
  return SemVer{std::stoll(m[1]), std::stoll(m[2]), std::stoll(m[3])};
}

int SemVer::compare(const SemVer& o) const {
  if (major != o.major) return major < o.major ? -1 : 1;
  if (minor != o.minor) return minor < o.minor ? -1 : 1;
  if (patch != o.patch) return patch < o.patch ? -1 : 1;
  return 0;
}

bool is_safe_identifier(const std::string& s) {
  static const std::regex re(R"(^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$)");
  return std::regex_match(s, re) && s.find("..") == std::string::npos;
}

FirmwareManifest FirmwareManifest::from_json(const json::Value& v) {
  FirmwareManifest m;
  m.firmware_id = v.str("firmware_id");
  m.version = v.str("version");
  m.hardware_id = v.str("hardware_id");
  m.sha256 = v.str("sha256");
  m.size = v.integer("size");
  m.security_counter = v.integer("security_counter");
  m.min_current_version = v.str("min_current_version");
  m.key_id = v.str("key_id");
  m.signature_b64 = v.str("signature");
  m.release_notes = v.has("release_notes") ? v.str("release_notes") : "";
  m.simulate_unhealthy = v.has("simulate_unhealthy") && v.at("simulate_unhealthy").as_bool();
  return m;
}

std::string FirmwareManifest::signing_payload() const {
  std::ostringstream os;
  auto field = [&](const char* name, const std::string& value) {
    os << name << '=' << value.size() << ':' << value << '\n';
  };
  os << "AUTOLINK-FW-MANIFEST-V1\n";
  field("firmware_id", firmware_id);
  field("version", version);
  field("hardware_id", hardware_id);
  field("sha256", sha256);
  field("size", std::to_string(size));
  field("security_counter", std::to_string(security_counter));
  field("min_current_version", min_current_version);
  field("key_id", key_id);
  field("release_notes", release_notes);
  field("simulate_unhealthy", simulate_unhealthy ? "true" : "false");
  return os.str();
}

const char* to_string(VerifyError e) {
  switch (e) {
    case VerifyError::NONE: return "NONE";
    case VerifyError::MALFORMED: return "MALFORMED";
    case VerifyError::UNKNOWN_KEY: return "UNKNOWN_KEY";
    case VerifyError::REVOKED_KEY: return "REVOKED_KEY";
    case VerifyError::BAD_SIGNATURE: return "BAD_SIGNATURE";
    case VerifyError::WRONG_HARDWARE: return "WRONG_HARDWARE";
    case VerifyError::ROLLBACK: return "ROLLBACK";
    case VerifyError::INCOMPATIBLE_VERSION: return "INCOMPATIBLE_VERSION";
    case VerifyError::TOO_LARGE: return "TOO_LARGE";
    case VerifyError::DIGEST_MISMATCH: return "DIGEST_MISMATCH";
    case VerifyError::SIZE_MISMATCH: return "SIZE_MISMATCH";
  }
  return "UNKNOWN";
}

void TrustStore::add_key(const std::string& key_id, const crypto::Bytes& public_key) {
  keys_[key_id] = public_key;
}

TrustStore TrustStore::from_json(const json::Value& v) {
  TrustStore t;
  for (const auto& k : v.at("keys").as_array()) {
    crypto::Bytes pk;
    if (!crypto::base64_decode(k.str("public_key_b64"), pk) || pk.size() != 32)
      throw std::runtime_error("trust store: invalid public key for " + k.str("key_id"));
    t.add_key(k.str("key_id"), pk);
  }
  if (v.has("revoked"))
    for (const auto& r : v.at("revoked").as_array()) t.revoke(r.as_string());
  return t;
}

const crypto::Bytes* TrustStore::find(const std::string& key_id) const {
  auto it = keys_.find(key_id);
  return it == keys_.end() ? nullptr : &it->second;
}

VerifyResult verify_manifest(const FirmwareManifest& m, const TrustStore& trust,
                             const EcuIdentity& ecu) {
  // 1. Structural validation (fail closed on anything unexpected).
  static const std::regex hex64(R"(^[0-9a-f]{64}$)");
  if (!is_safe_identifier(m.firmware_id) || !is_safe_identifier(m.key_id) ||
      !std::regex_match(m.sha256, hex64) || m.size <= 0 || m.security_counter < 0)
    return {VerifyError::MALFORMED, "manifest field validation failed"};
  auto target = SemVer::parse(m.version);
  auto min_cur = SemVer::parse(m.min_current_version);
  auto current = SemVer::parse(ecu.current_version);
  if (!target || !min_cur || !current) return {VerifyError::MALFORMED, "invalid version string"};
  if (m.size > kMaxFirmwareBytes) return {VerifyError::TOO_LARGE, "package exceeds size limit"};

  // 2. Authenticity: signature must verify under a trusted, non-revoked key.
  if (trust.is_revoked(m.key_id)) return {VerifyError::REVOKED_KEY, "signing key revoked"};
  const crypto::Bytes* pk = trust.find(m.key_id);
  if (!pk) return {VerifyError::UNKNOWN_KEY, "signing key not trusted"};
  crypto::Bytes sig;
  if (!crypto::base64_decode(m.signature_b64, sig))
    return {VerifyError::BAD_SIGNATURE, "signature not valid base64"};
  if (!crypto::ed25519_verify(*pk, sig, m.signing_payload()))
    return {VerifyError::BAD_SIGNATURE, "Ed25519 signature verification failed"};

  // 3. Policy on authenticated fields.
  if (m.hardware_id != ecu.hardware_id)
    return {VerifyError::WRONG_HARDWARE, "target " + m.hardware_id + " != " + ecu.hardware_id};
  if (m.security_counter < ecu.min_security_counter)
    return {VerifyError::ROLLBACK, "security counter below anti-rollback floor"};
  if (target->compare(*current) <= 0)
    return {VerifyError::ROLLBACK, "version " + m.version + " not newer than " + ecu.current_version};
  if (current->compare(*min_cur) < 0)
    return {VerifyError::INCOMPATIBLE_VERSION, "requires current >= " + m.min_current_version};
  return {};
}

VerifyResult verify_image(const FirmwareManifest& m, const std::string& image_path) {
  struct stat st {};
  if (::stat(image_path.c_str(), &st) != 0) return {VerifyError::SIZE_MISMATCH, "image missing"};
  if (st.st_size != m.size) return {VerifyError::SIZE_MISMATCH, "image size differs from manifest"};
  std::string digest = crypto::sha256_file_hex(image_path);
  if (!crypto::constant_time_equal(digest, m.sha256))
    return {VerifyError::DIGEST_MISMATCH, "SHA-256 digest mismatch"};
  return {};
}

}  // namespace autolink
