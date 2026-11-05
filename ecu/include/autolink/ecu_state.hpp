// Persistent ECU state and the atomic store that protects it across simulated
// power loss (REQ-ECU-005, REQ-ECU-006).
#pragma once

#include <cstdint>
#include <deque>
#include <string>
#include <vector>

#include "autolink/json.hpp"
#include "autolink/update_state.hpp"

namespace autolink {

struct SlotInfo {
  std::string firmware_id;  // empty = slot never written
  std::string version;
  std::string sha256;
  int64_t security_counter = 0;
};

struct PendingUpdate {
  int64_t command_seq = 0;
  std::string deployment_id;
  std::string firmware_id;
  std::string version;
  std::string sha256;
  int64_t size = 0;
  int64_t security_counter = 0;
  bool simulate_unhealthy = false;  // signed release metadata (simulation only)
  int download_attempts = 0;
  std::string last_error;
};

struct DiagnosticTroubleCode {
  std::string code;
  std::string severity;  // INFO | WARNING | ERROR | CRITICAL
  std::string description;
  std::string deployment_id;
  int64_t timestamp = 0;
};

struct Counters {
  int64_t heartbeats_sent = 0;
  int64_t updates_attempted = 0;
  int64_t updates_committed = 0;
  int64_t rollbacks = 0;
  int64_t verification_failures = 0;
  int64_t download_retries = 0;
  int64_t bytes_downloaded = 0;
  int64_t commands_rejected = 0;
  int64_t duplicate_commands = 0;
  int64_t boots = 0;
};

struct EcuState {
  std::string vehicle_id;
  std::string ecu_id;
  std::string hardware_id;
  char active_slot = 'A';
  char last_known_good_slot = 'A';
  SlotInfo slot_a;
  SlotInfo slot_b;
  UpdateState update_state = UpdateState::IDLE;
  PendingUpdate pending;
  int64_t min_security_counter = 0;  // anti-rollback floor
  int64_t last_command_seq = 0;      // replay protection
  int64_t next_event_seq = 1;        // per-ECU monotonic event id for backend dedup
  std::vector<DiagnosticTroubleCode> dtcs;
  std::deque<std::string> outbox;  // un-acknowledged event JSON (bounded)
  Counters counters;

  SlotInfo& slot(char s) { return s == 'A' ? slot_a : slot_b; }
  const SlotInfo& slot(char s) const { return s == 'A' ? slot_a : slot_b; }
  char inactive_slot() const { return active_slot == 'A' ? 'B' : 'A'; }
  const SlotInfo& active() const { return slot(active_slot); }

  json::Value to_json() const;
  static EcuState from_json(const json::Value& v);
};

constexpr size_t kMaxOutboxEvents = 256;
constexpr size_t kMaxStoredDtcs = 64;

// Atomic file store: write-to-temp, fsync, rename, fsync(dir). A crash at any
// point leaves either the old or the new complete state on disk.
class StateStore {
 public:
  explicit StateStore(std::string path) : path_(std::move(path)) {}
  bool exists() const;
  EcuState load() const;
  void save(const EcuState& s) const;
  const std::string& path() const { return path_; }

 private:
  std::string path_;
};

// Append-only, fsync'd update journal (human-auditable history of transitions).
class Journal {
 public:
  explicit Journal(std::string path) : path_(std::move(path)) {}
  void append(const json::Value& entry) const;
  std::vector<std::string> read_all() const;

 private:
  std::string path_;
};

// Durably writes `data` to `path` using the temp+rename pattern.
void atomic_write_file(const std::string& path, const std::string& data);

}  // namespace autolink
