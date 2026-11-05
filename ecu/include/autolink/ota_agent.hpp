// OTA agent: owns the ECU state, drives the update state machine, runs the
// recovery supervisor at boot, and talks to the cloud through CloudLink.
#pragma once

#include <cstdint>
#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "autolink/ecu_state.hpp"
#include "autolink/manifest.hpp"

namespace autolink {

class TransportError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

struct Command {
  int64_t seq = 0;
  std::string type;  // "install"
  std::string vehicle_id;
  std::string deployment_id;
  std::string firmware_id;
  int64_t expires_at = 0;  // unix seconds
  static Command from_json(const json::Value& v);
};

// Abstract vehicle-to-cloud channel. HttpCloudLink is the real implementation;
// unit tests use an in-memory fake.
class CloudLink {
 public:
  virtual ~CloudLink() = default;
  // Sends heartbeat/telemetry; returns pending commands newer than the ECU's last seq.
  virtual std::vector<Command> heartbeat(const json::Value& body) = 0;
  virtual json::Value fetch_manifest(const std::string& firmware_id) = 0;
  // Appends bytes [offset, end) of the image to dest. `on_progress(total_bytes)`
  // returning false aborts the transfer (used for fault injection).
  virtual void download(const std::string& firmware_id, const std::string& dest, int64_t offset,
                        int64_t max_total, const std::function<bool(int64_t)>& on_progress) = 0;
  virtual void post_events(const std::vector<std::string>& events) = 0;
};

// Deterministic fault hooks (simulation only; see experiments/).
struct FaultConfig {
  std::optional<UpdateState> crash_after_entering;  // simulated power loss
  int64_t interrupt_download_after_bytes = -1;      // first attempt only
  bool corrupt_downloaded_image = false;
  bool health_check_fail = false;
  bool recovery_fail = false;
  bool replay_commands = false;  // deliver each command batch twice
};

constexpr int kPowerLossExitCode = 86;
constexpr int kMaxDownloadAttempts = 5;

struct AgentConfig {
  std::string state_dir;
  std::string vehicle_id;
  std::string ecu_id;
  std::string hardware_id;
  std::string factory_version = "1.0.0";
  int backoff_base_ms = 200;
  int backoff_max_ms = 5000;
};

class OtaAgent {
 public:
  using Clock = std::function<int64_t()>;
  using Sleeper = std::function<void(int ms)>;

  OtaAgent(AgentConfig cfg, CloudLink& link, TrustStore trust, FaultConfig faults = {},
           Clock clock = nullptr, Sleeper sleeper = nullptr);

  // Loads (or provisions) persistent state and resumes/recovers any update that
  // was interrupted by a restart or power loss.
  void boot();
  // One connectivity cycle: heartbeat, command handling, update progress, outbox flush.
  // Returns false if the cloud was unreachable.
  bool cycle();
  void handle_commands(const std::vector<Command>& cmds);
  // Drives the pending update until the state machine is quiescent.
  void run_update();
  bool flush_outbox();
  // Clears a RECOVERY_FAILED latch (service tool action).
  void service_reset();

  const EcuState& state() const { return st_; }
  std::string slot_path(char slot) const;
  std::string download_path() const;

 private:
  void transition(UpdateState to, const std::string& detail, const std::string& error_code = "");
  void record_dtc(const std::string& code, const std::string& severity, const std::string& desc);
  void enqueue_event(json::Object ev);
  void persist();
  json::Value heartbeat_body() const;
  void provision_factory_image();
  void resume_after_boot();
  void step();  // executes the action for the current state

  void do_download();
  void do_verify();
  void do_stage();
  void do_activate();
  void do_health_check();
  void do_recovery();
  void finish_to_idle();

  AgentConfig cfg_;
  CloudLink& link_;
  TrustStore trust_;
  FaultConfig faults_;
  Clock clock_;
  Sleeper sleep_;
  StateStore store_;
  Journal journal_;
  EcuState st_;
  bool interrupt_used_ = false;
  uint64_t telemetry_tick_ = 0;
};

}  // namespace autolink
