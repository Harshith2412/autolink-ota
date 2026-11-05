#include "autolink/ota_agent.hpp"

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <ctime>
#include <fstream>
#include <iostream>
#include <sstream>
#include <thread>

namespace autolink {
namespace {

constexpr int kMaxStepsPerRun = 64;
constexpr size_t kCopyChunk = 64 * 1024;

// Simulated, manufacturer-specific DTC range (not real OEM codes).
namespace dtc {
constexpr const char* kSignatureInvalid = "U3001";
constexpr const char* kDigestMismatch = "U3002";
constexpr const char* kIncompatible = "U3003";
constexpr const char* kRollbackAttempt = "U3004";
constexpr const char* kMalformedPackage = "U3005";
constexpr const char* kDownloadFailed = "U3010";
constexpr const char* kDownloadAbandoned = "U3011";
constexpr const char* kStagingFailed = "U3020";
constexpr const char* kHealthCheckFailed = "U3030";
constexpr const char* kRolledBack = "U3031";
constexpr const char* kRecoveryFailed = "U3040";
constexpr const char* kCommandRejected = "U3050";
}  // namespace dtc

const char* dtc_for(VerifyError e) {
  switch (e) {
    case VerifyError::BAD_SIGNATURE:
    case VerifyError::UNKNOWN_KEY:
    case VerifyError::REVOKED_KEY: return dtc::kSignatureInvalid;
    case VerifyError::DIGEST_MISMATCH:
    case VerifyError::SIZE_MISMATCH: return dtc::kDigestMismatch;
    case VerifyError::WRONG_HARDWARE:
    case VerifyError::INCOMPATIBLE_VERSION: return dtc::kIncompatible;
    case VerifyError::ROLLBACK: return dtc::kRollbackAttempt;
    default: return dtc::kMalformedPackage;
  }
}

int64_t file_size(const std::string& path) {
  struct stat st {};
  return ::stat(path.c_str(), &st) == 0 ? static_cast<int64_t>(st.st_size) : -1;
}

std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("cannot read " + path);
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

// Copies src to dst via temp file + fsync + rename so a slot is never half-written.
void copy_file_atomic(const std::string& src, const std::string& dst) {
  std::ifstream in(src, std::ios::binary);
  if (!in) throw std::runtime_error("cannot open " + src);
  const std::string tmp = dst + ".tmp";
  int fd = ::open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
  if (fd < 0) throw std::runtime_error("cannot create " + tmp);
  std::vector<char> buf(kCopyChunk);
  bool ok = true;
  while (ok && in) {
    in.read(buf.data(), static_cast<std::streamsize>(buf.size()));
    std::streamsize n = in.gcount();
    for (std::streamsize off = 0; ok && off < n;) {
      ssize_t w = ::write(fd, buf.data() + off, static_cast<size_t>(n - off));
      if (w < 0) {
        if (errno == EINTR) continue;
        ok = false;
      } else {
        off += w;
      }
    }
  }
  ok = ok && !in.bad() && ::fsync(fd) == 0;
  ok = (::close(fd) == 0) && ok;
  if (!ok) {
    ::unlink(tmp.c_str());
    throw std::runtime_error("failed to write " + tmp);
  }
  if (::rename(tmp.c_str(), dst.c_str()) != 0) throw std::runtime_error("rename failed for " + dst);
}

void flip_middle_byte(const std::string& path) {
  std::fstream f(path, std::ios::in | std::ios::out | std::ios::binary);
  if (!f) return;
  f.seekg(0, std::ios::end);
  auto sz = static_cast<int64_t>(f.tellg());
  if (sz <= 0) return;
  f.seekg(sz / 2);
  char c = 0;
  f.read(&c, 1);
  c = static_cast<char>(c ^ 0x5A);
  f.seekp(sz / 2);
  f.write(&c, 1);
}
}  // namespace

Command Command::from_json(const json::Value& v) {
  Command c;
  c.seq = v.integer("seq");
  c.type = v.str("type");
  c.vehicle_id = v.str("vehicle_id");
  c.deployment_id = v.str("deployment_id");
  c.firmware_id = v.str("firmware_id");
  c.expires_at = v.integer("expires_at");
  return c;
}

OtaAgent::OtaAgent(AgentConfig cfg, CloudLink& link, TrustStore trust, FaultConfig faults,
                   Clock clock, Sleeper sleeper)
    : cfg_(std::move(cfg)),
      link_(link),
      trust_(std::move(trust)),
      faults_(faults),
      clock_(clock ? std::move(clock) : Clock([] { return static_cast<int64_t>(std::time(nullptr)); })),
      sleep_(sleeper ? std::move(sleeper)
                     : Sleeper([](int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); })),
      store_(cfg_.state_dir + "/state.json"),
      journal_(cfg_.state_dir + "/journal.log") {}

std::string OtaAgent::slot_path(char slot) const {
  return cfg_.state_dir + "/slot_" + std::string(1, slot) + ".img";
}
std::string OtaAgent::download_path() const { return cfg_.state_dir + "/download.part"; }

void OtaAgent::persist() { store_.save(st_); }

void OtaAgent::provision_factory_image() {
  st_ = EcuState{};
  st_.vehicle_id = cfg_.vehicle_id;
  st_.ecu_id = cfg_.ecu_id;
  st_.hardware_id = cfg_.hardware_id;
  const std::string image = "AUTOLINK SIMULATED FACTORY FIRMWARE hw=" + cfg_.hardware_id +
                            " version=" + cfg_.factory_version + "\n";
  atomic_write_file(slot_path('A'), image);
  st_.slot_a = {"factory", cfg_.factory_version, crypto::sha256_hex(image), 0};
  st_.active_slot = 'A';
  st_.last_known_good_slot = 'A';
  persist();
  journal_.append(json::Object{{"ts", clock_()}, {"event", "PROVISIONED"},
                               {"version", cfg_.factory_version}});
}

void OtaAgent::boot() {
  if (store_.exists()) {
    st_ = store_.load();
    if (st_.vehicle_id != cfg_.vehicle_id || st_.hardware_id != cfg_.hardware_id)
      throw std::runtime_error("persistent state belongs to a different vehicle/hardware");
  } else {
    provision_factory_image();
  }
  st_.counters.boots++;
  journal_.append(json::Object{{"ts", clock_()}, {"event", "BOOT"},
                               {"state", std::string(to_string(st_.update_state))},
                               {"active_slot", std::string(1, st_.active_slot)},
                               {"version", st_.active().version}});
  persist();
  resume_after_boot();
}

void OtaAgent::resume_after_boot() {
  // Recovery supervisor: an interrupted update is resumed or rolled back based
  // on the last durably recorded state.
  switch (st_.update_state) {
    case UpdateState::DOWNLOADING:
      st_.pending.download_attempts++;
      transition(UpdateState::DOWNLOAD_FAILED, "download interrupted by restart/power loss",
                 "INTERRUPTED");
      break;
    case UpdateState::ACTIVATING:
    case UpdateState::HEALTH_CHECK:
      record_dtc(dtc::kHealthCheckFailed, "ERROR", "boot into new image was not confirmed");
      transition(UpdateState::ACTIVATION_FAILED, "unconfirmed boot after restart/power loss",
                 "UNCONFIRMED_BOOT");
      break;
    default:
      break;  // remaining states are resumed idempotently by step()
  }
  run_update();
}

void OtaAgent::transition(UpdateState to, const std::string& detail, const std::string& error_code) {
  const UpdateState from = st_.update_state;
  if (!is_valid_transition(from, to)) throw InvalidTransition(from, to);
  st_.update_state = to;
  const auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                          std::chrono::system_clock::now().time_since_epoch()).count();
  journal_.append(json::Object{{"ts", clock_()},
                               {"ts_ms", static_cast<int64_t>(now_ms)},
                               {"event", "TRANSITION"},
                               {"from", std::string(to_string(from))},
                               {"to", std::string(to_string(to))},
                               {"deployment_id", st_.pending.deployment_id},
                               {"detail", detail}});
  enqueue_event(json::Object{{"kind", "STATE"},
                             {"from_state", std::string(to_string(from))},
                             {"to_state", std::string(to_string(to))},
                             {"detail", detail},
                             {"error_code", error_code}});
  persist();
  if (faults_.crash_after_entering && *faults_.crash_after_entering == to) {
    std::cerr << "[fault] simulated power loss after entering " << to_string(to) << std::endl;
    std::_Exit(kPowerLossExitCode);
  }
  flush_outbox();
}

void OtaAgent::enqueue_event(json::Object ev) {
  ev["event_seq"] = st_.next_event_seq++;
  ev["vehicle_id"] = st_.vehicle_id;
  ev["ecu_id"] = st_.ecu_id;
  ev["deployment_id"] = st_.pending.deployment_id;
  ev["firmware_version"] = st_.active().version;
  ev["timestamp"] = clock_();
  st_.outbox.push_back(json::Value(std::move(ev)).dump());
  while (st_.outbox.size() > kMaxOutboxEvents) st_.outbox.pop_front();  // bounded
}

void OtaAgent::record_dtc(const std::string& code, const std::string& severity,
                          const std::string& desc) {
  DiagnosticTroubleCode d{code, severity, desc, st_.pending.deployment_id, clock_()};
  st_.dtcs.push_back(d);
  if (st_.dtcs.size() > kMaxStoredDtcs) st_.dtcs.erase(st_.dtcs.begin());
  enqueue_event(json::Object{{"kind", "DTC"},
                             {"code", code},
                             {"severity", severity},
                             {"description", desc}});
}

bool OtaAgent::flush_outbox() {
  if (st_.outbox.empty()) return true;
  std::vector<std::string> batch(st_.outbox.begin(), st_.outbox.end());
  try {
    link_.post_events(batch);
  } catch (const TransportError&) {
    return false;  // events stay queued and are retried; backend dedups by event_seq
  }
  st_.outbox.clear();
  persist();
  return true;
}

void OtaAgent::handle_commands(const std::vector<Command>& cmds) {
  std::vector<Command> sorted = cmds;
  std::sort(sorted.begin(), sorted.end(),
            [](const Command& a, const Command& b) { return a.seq < b.seq; });
  for (const auto& c : sorted) {
    if (c.seq <= st_.last_command_seq) {  // duplicate or out-of-order replay
      st_.counters.duplicate_commands++;
      journal_.append(json::Object{{"ts", clock_()}, {"event", "COMMAND_IGNORED_DUPLICATE"},
                                   {"seq", c.seq}});
      continue;
    }
    std::string reason;
    if (c.vehicle_id != st_.vehicle_id) reason = "command addressed to another vehicle";
    else if (c.type != "install") reason = "unsupported command type";
    else if (c.expires_at < clock_()) reason = "command expired";
    else if (!is_safe_identifier(c.firmware_id) || !is_safe_identifier(c.deployment_id))
      reason = "invalid identifiers";
    else if (st_.update_state != UpdateState::IDLE) reason = "update already in progress";

    st_.last_command_seq = c.seq;  // consumed either way: never re-executed
    if (!reason.empty()) {
      st_.counters.commands_rejected++;
      PendingUpdate saved = st_.pending;
      st_.pending.deployment_id = c.deployment_id;
      enqueue_event(json::Object{{"kind", "COMMAND_REJECTED"}, {"seq", c.seq}, {"detail", reason}});
      st_.pending = saved;
      persist();
      continue;
    }
    st_.pending = PendingUpdate{};
    st_.pending.command_seq = c.seq;
    st_.pending.deployment_id = c.deployment_id;
    st_.pending.firmware_id = c.firmware_id;
    st_.counters.updates_attempted++;
    ::unlink(download_path().c_str());
    ::unlink((cfg_.state_dir + "/pending_manifest.json").c_str());
    transition(UpdateState::UPDATE_AVAILABLE, "install command seq " + std::to_string(c.seq));
  }
  persist();
}

void OtaAgent::run_update() {
  for (int i = 0; i < kMaxStepsPerRun && !is_quiescent(st_.update_state); ++i) step();
}

void OtaAgent::step() {
  switch (st_.update_state) {
    case UpdateState::IDLE:
    case UpdateState::RECOVERY_FAILED:
      return;
    case UpdateState::UPDATE_AVAILABLE:
      transition(UpdateState::DOWNLOADING,
                 "download attempt " + std::to_string(st_.pending.download_attempts + 1));
      return;
    case UpdateState::DOWNLOADING:
      do_download();
      return;
    case UpdateState::DOWNLOAD_FAILED:
      if (st_.pending.download_attempts < kMaxDownloadAttempts) {
        int delay = std::min(cfg_.backoff_max_ms,
                             cfg_.backoff_base_ms << std::min(st_.pending.download_attempts, 10));
        sleep_(delay);
        st_.counters.download_retries++;
        transition(UpdateState::UPDATE_AVAILABLE, "retrying download after " +
                                                      std::to_string(delay) + " ms backoff");
      } else {
        record_dtc(dtc::kDownloadAbandoned, "ERROR", "download abandoned after max attempts");
        finish_to_idle();
      }
      return;
    case UpdateState::VERIFYING:
      do_verify();
      return;
    case UpdateState::STAGING:
      do_stage();
      return;
    case UpdateState::READY_TO_ACTIVATE:
      do_activate();
      return;
    case UpdateState::ACTIVATING:
      st_.counters.boots++;
      transition(UpdateState::HEALTH_CHECK,
                 "simulated reboot into slot " + std::string(1, st_.active_slot));
      return;
    case UpdateState::HEALTH_CHECK:
      do_health_check();
      return;
    case UpdateState::ACTIVATION_FAILED:
      transition(UpdateState::RECOVERY_IN_PROGRESS, "reverting to last known-good slot");
      return;
    case UpdateState::RECOVERY_IN_PROGRESS:
      do_recovery();
      return;
    case UpdateState::VERIFICATION_FAILED:
    case UpdateState::STAGING_FAILED:
    case UpdateState::COMMITTED:
    case UpdateState::ROLLED_BACK:
      finish_to_idle();
      return;
  }
}

void OtaAgent::do_download() {
  const std::string manifest_path = cfg_.state_dir + "/pending_manifest.json";
  try {
    if (file_size(manifest_path) <= 0) {
      json::Value m = link_.fetch_manifest(st_.pending.firmware_id);
      atomic_write_file(manifest_path, m.dump());
    }
    auto manifest = json::parse(read_file(manifest_path));
    int64_t expected = manifest.integer("size");
    int64_t max_total = std::min(expected, kMaxFirmwareBytes);
    int64_t offset = std::max<int64_t>(0, file_size(download_path()));
    if (offset > max_total) {
      ::unlink(download_path().c_str());
      offset = 0;
    }
    int64_t last_total = offset;
    auto progress = [&](int64_t total) {
      st_.counters.bytes_downloaded += total - last_total;
      last_total = total;
      if (!interrupt_used_ && faults_.interrupt_download_after_bytes >= 0 &&
          total >= faults_.interrupt_download_after_bytes) {
        interrupt_used_ = true;
        return false;
      }
      return true;
    };
    if (offset < max_total) link_.download(st_.pending.firmware_id, download_path(), offset, max_total, progress);
  } catch (const std::exception& e) {
    // TransportError, a truncated/oversized body, or a malformed manifest: all retryable.
    st_.pending.download_attempts++;
    st_.pending.last_error = e.what();
    record_dtc(dtc::kDownloadFailed, "WARNING", std::string("download failed: ") + e.what());
    transition(UpdateState::DOWNLOAD_FAILED, e.what(), "DOWNLOAD_ERROR");
    return;
  }
  if (faults_.corrupt_downloaded_image) flip_middle_byte(download_path());
  transition(UpdateState::VERIFYING, "downloaded " + std::to_string(file_size(download_path())) + " bytes");
}

void OtaAgent::do_verify() {
  FirmwareManifest m;
  VerifyResult r;
  try {
    m = FirmwareManifest::from_json(json::parse(read_file(cfg_.state_dir + "/pending_manifest.json")));
    if (m.firmware_id != st_.pending.firmware_id) {
      r = {VerifyError::MALFORMED, "manifest firmware_id does not match command"};
    } else {
      r = verify_manifest(m, trust_, {st_.hardware_id, st_.active().version, st_.min_security_counter});
      if (r.ok()) r = verify_image(m, download_path());
    }
  } catch (const std::exception& e) {
    r = {VerifyError::MALFORMED, e.what()};
  }
  if (!r.ok()) {
    st_.counters.verification_failures++;
    record_dtc(dtc_for(r.error), "ERROR", std::string(to_string(r.error)) + ": " + r.detail);
    transition(UpdateState::VERIFICATION_FAILED, r.detail, to_string(r.error));
    return;
  }
  st_.pending.version = m.version;
  st_.pending.sha256 = m.sha256;
  st_.pending.size = m.size;
  st_.pending.security_counter = m.security_counter;
  st_.pending.simulate_unhealthy = m.simulate_unhealthy;
  transition(UpdateState::STAGING, "signature, policy and SHA-256 verified for " + m.version);
}

void OtaAgent::do_stage() {
  const char target = st_.inactive_slot();
  try {
    copy_file_atomic(download_path(), slot_path(target));
    std::string digest = crypto::sha256_file_hex(slot_path(target));
    if (!crypto::constant_time_equal(digest, st_.pending.sha256))
      throw std::runtime_error("staged image digest mismatch");
  } catch (const std::exception& e) {
    record_dtc(dtc::kStagingFailed, "ERROR", e.what());
    transition(UpdateState::STAGING_FAILED, e.what(), "STAGING_ERROR");
    return;
  }
  st_.slot(target) = {st_.pending.firmware_id, st_.pending.version, st_.pending.sha256,
                      st_.pending.security_counter};
  transition(UpdateState::READY_TO_ACTIVATE, "staged into slot " + std::string(1, target));
}

void OtaAgent::do_activate() {
  const char target = st_.inactive_slot();
  st_.active_slot = target;  // persisted atomically together with the transition
  transition(UpdateState::ACTIVATING, "boot slot set to " + std::string(1, target));
}

void OtaAgent::do_health_check() {
  std::string reason;
  try {
    if (!crypto::constant_time_equal(crypto::sha256_file_hex(slot_path(st_.active_slot)),
                                     st_.active().sha256))
      reason = "active slot digest mismatch";
  } catch (const std::exception& e) {
    reason = e.what();
  }
  if (reason.empty() && st_.pending.simulate_unhealthy) reason = "firmware self-test reported failure";
  if (reason.empty() && faults_.health_check_fail) reason = "injected health-check failure";
  if (!reason.empty()) {
    record_dtc(dtc::kHealthCheckFailed, "ERROR", reason);
    transition(UpdateState::ACTIVATION_FAILED, reason, "HEALTH_CHECK_FAILED");
    return;
  }
  st_.last_known_good_slot = st_.active_slot;
  st_.min_security_counter = std::max(st_.min_security_counter, st_.active().security_counter);
  st_.counters.updates_committed++;
  transition(UpdateState::COMMITTED, "health check passed; " + st_.active().version + " committed");
}

void OtaAgent::do_recovery() {
  const char lkg = st_.last_known_good_slot;
  if (faults_.recovery_fail) {
    std::ofstream(slot_path(lkg), std::ios::app | std::ios::binary) << '\x00';
  }
  bool intact = false;
  try {
    intact = crypto::constant_time_equal(crypto::sha256_file_hex(slot_path(lkg)), st_.slot(lkg).sha256);
  } catch (const std::exception&) {
    intact = false;
  }
  if (!intact) {
    record_dtc(dtc::kRecoveryFailed, "CRITICAL", "last known-good image failed integrity check");
    transition(UpdateState::RECOVERY_FAILED, "last known-good image corrupt; service required",
               "RECOVERY_FAILED");
    return;
  }
  const char failed = st_.active_slot == lkg ? st_.inactive_slot() : st_.active_slot;
  st_.active_slot = lkg;
  st_.slot(failed) = SlotInfo{};
  st_.counters.rollbacks++;
  record_dtc(dtc::kRolledBack, "WARNING", "rolled back to " + st_.slot(lkg).version);
  transition(UpdateState::ROLLED_BACK, "restored slot " + std::string(1, lkg) + " (" +
                                           st_.slot(lkg).version + ")");
}

void OtaAgent::finish_to_idle() {
  ::unlink(download_path().c_str());
  ::unlink((cfg_.state_dir + "/pending_manifest.json").c_str());
  transition(UpdateState::IDLE, "update cycle finished");
  st_.pending = PendingUpdate{};
  persist();
}

void OtaAgent::service_reset() {
  if (st_.update_state != UpdateState::RECOVERY_FAILED) return;
  journal_.append(json::Object{{"ts", clock_()}, {"event", "SERVICE_RESET"}});
  st_.update_state = UpdateState::IDLE;
  st_.pending = PendingUpdate{};
  persist();
}

json::Value OtaAgent::heartbeat_body() const {
  // Deterministic simulated signals so experiments are reproducible.
  const double t = static_cast<double>(telemetry_tick_);
  json::Object telemetry{{"speed_kph", std::round((50.0 + 20.0 * std::sin(t / 5.0)) * 10) / 10},
                         {"battery_v", std::round((12.6 - 0.2 * std::cos(t / 7.0)) * 100) / 100},
                         {"coolant_c", std::round((85.0 + 5.0 * std::sin(t / 11.0)) * 10) / 10},
                         {"rssi_dbm", -70 + static_cast<int>(telemetry_tick_ % 15)}};
  const auto& c = st_.counters;
  return json::Object{
      {"vehicle_id", st_.vehicle_id},
      {"ecu_id", st_.ecu_id},
      {"hardware_id", st_.hardware_id},
      {"firmware_version", st_.active().version},
      {"active_slot", std::string(1, st_.active_slot)},
      {"update_state", std::string(to_string(st_.update_state))},
      {"last_command_seq", st_.last_command_seq},
      {"telemetry", telemetry},
      {"counters", json::Object{{"updates_committed", c.updates_committed},
                                {"rollbacks", c.rollbacks},
                                {"verification_failures", c.verification_failures},
                                {"download_retries", c.download_retries},
                                {"bytes_downloaded", c.bytes_downloaded},
                                {"duplicate_commands", c.duplicate_commands},
                                {"boots", c.boots}}},
  };
}

bool OtaAgent::cycle() {
  std::vector<Command> cmds;
  try {
    cmds = link_.heartbeat(heartbeat_body());
  } catch (const TransportError& e) {
    std::cerr << "[link] heartbeat failed: " << e.what() << std::endl;
    return false;
  }
  telemetry_tick_++;
  st_.counters.heartbeats_sent++;
  handle_commands(cmds);
  if (faults_.replay_commands) handle_commands(cmds);
  run_update();
  flush_outbox();
  persist();
  return true;
}

}  // namespace autolink
