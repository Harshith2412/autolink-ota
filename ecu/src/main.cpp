// autolink-ecu: simulated automotive ECU with a secure OTA client.
// Usage: autolink-ecu --config ecu/config/ecu.example.json [options]
#include <csignal>
#include <cstring>
#include <fstream>
#include <iostream>
#include <random>
#include <sstream>
#include <sys/stat.h>
#include <thread>

#include "autolink/http_link.hpp"
#include "autolink/ota_agent.hpp"

using namespace autolink;

namespace {
volatile std::sig_atomic_t g_stop = 0;
void on_signal(int) { g_stop = 1; }

constexpr int kExitOk = 0;
constexpr int kExitConfig = 2;
constexpr int kExitRecoveryFailed = 3;
constexpr int kExitTimeout = 4;

struct Options {
  std::string config_path;
  std::string state_dir_override;
  int max_cycles = 0;  // 0 = run until signalled
  bool exit_after_update = false;
  bool status_only = false;
  bool service_reset = false;
  uint32_t seed = 1;
  FaultConfig faults;
};

void usage() {
  std::cerr << "usage: autolink-ecu --config FILE [--state-dir DIR] [--cycles N] [--exit-after-update]\n"
               "                    [--status] [--service-reset] [--seed N]\n"
               "  fault injection (simulation only):\n"
               "    --crash-after STATE  --interrupt-download-after BYTES  --corrupt-download\n"
               "    --health-check-fail  --recovery-fail  --replay-commands\n";
}

std::string slurp(const std::string& p) {
  std::ifstream in(p);
  if (!in) throw std::runtime_error("cannot read " + p);
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

Options parse_args(int argc, char** argv) {
  Options o;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    auto need = [&]() -> std::string {
      if (i + 1 >= argc) throw std::invalid_argument("missing value for " + a);
      return argv[++i];
    };
    if (a == "--config") o.config_path = need();
    else if (a == "--state-dir") o.state_dir_override = need();
    else if (a == "--cycles") o.max_cycles = std::stoi(need());
    else if (a == "--exit-after-update") o.exit_after_update = true;
    else if (a == "--status") o.status_only = true;
    else if (a == "--service-reset") o.service_reset = true;
    else if (a == "--seed") o.seed = static_cast<uint32_t>(std::stoul(need()));
    else if (a == "--crash-after") {
      auto s = state_from_string(need());
      if (!s) throw std::invalid_argument("unknown state for --crash-after");
      o.faults.crash_after_entering = *s;
    } else if (a == "--interrupt-download-after") o.faults.interrupt_download_after_bytes = std::stoll(need());
    else if (a == "--corrupt-download") o.faults.corrupt_downloaded_image = true;
    else if (a == "--health-check-fail") o.faults.health_check_fail = true;
    else if (a == "--recovery-fail") o.faults.recovery_fail = true;
    else if (a == "--replay-commands") o.faults.replay_commands = true;
    else if (a == "--help" || a == "-h") {
      usage();
      std::exit(kExitOk);
    } else throw std::invalid_argument("unknown option " + a);
  }
  if (o.config_path.empty()) throw std::invalid_argument("--config is required");
  return o;
}
}  // namespace

int main(int argc, char** argv) {
  Options opt;
  json::Value cfg;
  try {
    opt = parse_args(argc, argv);
    cfg = json::parse(slurp(opt.config_path));
  } catch (const std::exception& e) {
    std::cerr << "error: " << e.what() << "\n";
    usage();
    return kExitConfig;
  }
  std::signal(SIGINT, on_signal);
  std::signal(SIGTERM, on_signal);

  try {
    AgentConfig ac;
    ac.state_dir = opt.state_dir_override.empty() ? cfg.str("state_dir") : opt.state_dir_override;
    ac.vehicle_id = cfg.str("vehicle_id");
    ac.ecu_id = cfg.str("ecu_id");
    ac.hardware_id = cfg.str("hardware_id");
    if (cfg.has("factory_version")) ac.factory_version = cfg.str("factory_version");
    if (cfg.has("backoff_base_ms")) ac.backoff_base_ms = static_cast<int>(cfg.integer("backoff_base_ms"));
    const int heartbeat_ms = cfg.has("heartbeat_ms") ? static_cast<int>(cfg.integer("heartbeat_ms")) : 2000;
    const int timeout_ms = cfg.has("http_timeout_ms") ? static_cast<int>(cfg.integer("http_timeout_ms")) : 3000;
    ::mkdir(ac.state_dir.c_str(), 0700);

    // Device credential: prefer the environment so it is not committed in config.
    const char* env_token = std::getenv("AUTOLINK_DEVICE_TOKEN");
    std::string token = env_token ? env_token : (cfg.has("device_token") ? cfg.str("device_token") : "");
    if (token.empty()) throw std::runtime_error("no device token (set AUTOLINK_DEVICE_TOKEN)");

    TrustStore trust = TrustStore::from_json(json::parse(slurp(cfg.str("trust_store"))));
    HttpCloudLink link(cfg.str("backend_url"), ac.vehicle_id, token, timeout_ms);
    OtaAgent agent(ac, link, std::move(trust), opt.faults);

    StateStore probe(ac.state_dir + "/state.json");
    const bool resumed = probe.exists() && probe.load().update_state != UpdateState::IDLE;
    agent.boot();

    if (opt.service_reset) agent.service_reset();
    if (opt.status_only || opt.service_reset) {
      std::cout << agent.state().to_json().dump() << std::endl;
      return kExitOk;
    }
    const int64_t attempts_at_start = agent.state().counters.updates_attempted;

    std::mt19937 rng(opt.seed);
    int failures = 0;
    for (int cycle = 0; !g_stop && (opt.max_cycles == 0 || cycle < opt.max_cycles); ++cycle) {
      bool ok = agent.cycle();
      const auto& s = agent.state();
      if (s.update_state == UpdateState::RECOVERY_FAILED && s.outbox.empty()) {
        std::cerr << "[ecu] RECOVERY_FAILED: service required" << std::endl;
        return kExitRecoveryFailed;
      }
      if (opt.exit_after_update && is_quiescent(s.update_state) && s.outbox.empty() &&
          (resumed || s.counters.updates_attempted > attempts_at_start)) {
        agent.cycle();  // final heartbeat so the cloud sees the resulting firmware version
        std::cout << s.to_json().dump() << std::endl;
        return kExitOk;
      }
      int delay = heartbeat_ms;
      if (!ok) {
        // Exponential backoff with full jitter, bounded.
        failures = std::min(failures + 1, 6);
        int cap = std::min(ac.backoff_base_ms << failures, 10000);
        delay = std::uniform_int_distribution<int>(ac.backoff_base_ms, std::max(ac.backoff_base_ms, cap))(rng);
      } else {
        failures = 0;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(delay));
    }
    if (opt.exit_after_update) {
      std::cout << agent.state().to_json().dump() << std::endl;
      return kExitTimeout;
    }
  } catch (const std::exception& e) {
    std::cerr << "fatal: " << e.what() << std::endl;
    return kExitConfig;
  }
  return kExitOk;
}
