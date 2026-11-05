#include "autolink/ecu_state.hpp"

#include <fcntl.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace autolink {
namespace {

json::Value slot_to_json(const SlotInfo& s) {
  return json::Object{{"firmware_id", s.firmware_id},
                      {"version", s.version},
                      {"sha256", s.sha256},
                      {"security_counter", s.security_counter}};
}
SlotInfo slot_from_json(const json::Value& v) {
  SlotInfo s;
  s.firmware_id = v.str("firmware_id");
  s.version = v.str("version");
  s.sha256 = v.str("sha256");
  s.security_counter = v.integer("security_counter");
  return s;
}

std::string dirname_of(const std::string& path) {
  auto pos = path.find_last_of('/');
  if (pos == std::string::npos) return ".";
  if (pos == 0) return "/";
  return path.substr(0, pos);
}

[[noreturn]] void throw_errno(const std::string& what) {
  throw std::runtime_error(what + ": " + std::strerror(errno));
}

class Fd {
 public:
  explicit Fd(int fd) : fd_(fd) {}
  ~Fd() {
    if (fd_ >= 0) ::close(fd_);
  }
  Fd(const Fd&) = delete;
  Fd& operator=(const Fd&) = delete;
  int get() const { return fd_; }
  void close_checked(const std::string& what) {
    int fd = fd_;
    fd_ = -1;
    if (::close(fd) != 0) throw_errno(what);
  }

 private:
  int fd_;
};

void write_all(int fd, const std::string& data, const std::string& what) {
  size_t off = 0;
  while (off < data.size()) {
    ssize_t n = ::write(fd, data.data() + off, data.size() - off);
    if (n < 0) {
      if (errno == EINTR) continue;
      throw_errno(what);
    }
    off += static_cast<size_t>(n);
  }
}
}  // namespace

json::Value EcuState::to_json() const {
  json::Array dtc_arr;
  for (const auto& d : dtcs)
    dtc_arr.push_back(json::Object{{"code", d.code},
                                   {"severity", d.severity},
                                   {"description", d.description},
                                   {"deployment_id", d.deployment_id},
                                   {"timestamp", d.timestamp}});
  json::Array outbox_arr(outbox.begin(), outbox.end());
  const auto& c = counters;
  return json::Object{
      {"schema_version", 1},
      {"vehicle_id", vehicle_id},
      {"ecu_id", ecu_id},
      {"hardware_id", hardware_id},
      {"active_slot", std::string(1, active_slot)},
      {"last_known_good_slot", std::string(1, last_known_good_slot)},
      {"slot_a", slot_to_json(slot_a)},
      {"slot_b", slot_to_json(slot_b)},
      {"update_state", std::string(to_string(update_state))},
      {"pending", json::Object{{"command_seq", pending.command_seq},
                               {"deployment_id", pending.deployment_id},
                               {"firmware_id", pending.firmware_id},
                               {"version", pending.version},
                               {"sha256", pending.sha256},
                               {"size", pending.size},
                               {"security_counter", pending.security_counter},
                               {"simulate_unhealthy", pending.simulate_unhealthy},
                               {"download_attempts", pending.download_attempts},
                               {"last_error", pending.last_error}}},
      {"min_security_counter", min_security_counter},
      {"last_command_seq", last_command_seq},
      {"next_event_seq", next_event_seq},
      {"dtcs", dtc_arr},
      {"outbox", outbox_arr},
      {"counters", json::Object{{"heartbeats_sent", c.heartbeats_sent},
                                {"updates_attempted", c.updates_attempted},
                                {"updates_committed", c.updates_committed},
                                {"rollbacks", c.rollbacks},
                                {"verification_failures", c.verification_failures},
                                {"download_retries", c.download_retries},
                                {"bytes_downloaded", c.bytes_downloaded},
                                {"commands_rejected", c.commands_rejected},
                                {"duplicate_commands", c.duplicate_commands},
                                {"boots", c.boots}}},
  };
}

EcuState EcuState::from_json(const json::Value& v) {
  if (v.integer("schema_version") != 1) throw std::runtime_error("unsupported state schema");
  EcuState s;
  s.vehicle_id = v.str("vehicle_id");
  s.ecu_id = v.str("ecu_id");
  s.hardware_id = v.str("hardware_id");
  auto slot_char = [](const std::string& x) {
    if (x != "A" && x != "B") throw std::runtime_error("corrupt state: bad slot id");
    return x[0];
  };
  s.active_slot = slot_char(v.str("active_slot"));
  s.last_known_good_slot = slot_char(v.str("last_known_good_slot"));
  s.slot_a = slot_from_json(v.at("slot_a"));
  s.slot_b = slot_from_json(v.at("slot_b"));
  auto st = state_from_string(v.str("update_state"));
  if (!st) throw std::runtime_error("corrupt state: unknown update_state");
  s.update_state = *st;
  const auto& p = v.at("pending");
  s.pending.command_seq = p.integer("command_seq");
  s.pending.deployment_id = p.str("deployment_id");
  s.pending.firmware_id = p.str("firmware_id");
  s.pending.version = p.str("version");
  s.pending.sha256 = p.str("sha256");
  s.pending.size = p.integer("size");
  s.pending.security_counter = p.integer("security_counter");
  s.pending.simulate_unhealthy = p.at("simulate_unhealthy").as_bool();
  s.pending.download_attempts = static_cast<int>(p.integer("download_attempts"));
  s.pending.last_error = p.str("last_error");
  s.min_security_counter = v.integer("min_security_counter");
  s.last_command_seq = v.integer("last_command_seq");
  s.next_event_seq = v.integer("next_event_seq");
  for (const auto& d : v.at("dtcs").as_array())
    s.dtcs.push_back({d.str("code"), d.str("severity"), d.str("description"),
                      d.str("deployment_id"), d.integer("timestamp")});
  for (const auto& e : v.at("outbox").as_array()) s.outbox.push_back(e.as_string());
  const auto& c = v.at("counters");
  s.counters.heartbeats_sent = c.integer("heartbeats_sent");
  s.counters.updates_attempted = c.integer("updates_attempted");
  s.counters.updates_committed = c.integer("updates_committed");
  s.counters.rollbacks = c.integer("rollbacks");
  s.counters.verification_failures = c.integer("verification_failures");
  s.counters.download_retries = c.integer("download_retries");
  s.counters.bytes_downloaded = c.integer("bytes_downloaded");
  s.counters.commands_rejected = c.integer("commands_rejected");
  s.counters.duplicate_commands = c.integer("duplicate_commands");
  s.counters.boots = c.integer("boots");
  return s;
}

void atomic_write_file(const std::string& path, const std::string& data) {
  const std::string tmp = path + ".tmp";
  {
    Fd fd(::open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600));
    if (fd.get() < 0) throw_errno("open " + tmp);
    write_all(fd.get(), data, "write " + tmp);
    if (::fsync(fd.get()) != 0) throw_errno("fsync " + tmp);
    fd.close_checked("close " + tmp);
  }
  if (::rename(tmp.c_str(), path.c_str()) != 0) throw_errno("rename " + tmp);
  Fd dir(::open(dirname_of(path).c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC));
  if (dir.get() >= 0) ::fsync(dir.get());  // best effort; not all FS support dir fsync
}

bool StateStore::exists() const { return ::access(path_.c_str(), F_OK) == 0; }

EcuState StateStore::load() const {
  std::ifstream in(path_, std::ios::binary);
  if (!in) throw std::runtime_error("cannot open state file " + path_);
  std::stringstream ss;
  ss << in.rdbuf();
  return EcuState::from_json(json::parse(ss.str()));
}

void StateStore::save(const EcuState& s) const { atomic_write_file(path_, s.to_json().dump()); }

void Journal::append(const json::Value& entry) const {
  Fd fd(::open(path_.c_str(), O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600));
  if (fd.get() < 0) throw_errno("open journal " + path_);
  write_all(fd.get(), entry.dump() + "\n", "append journal");
  if (::fsync(fd.get()) != 0) throw_errno("fsync journal");
  fd.close_checked("close journal");
}

std::vector<std::string> Journal::read_all() const {
  std::vector<std::string> lines;
  std::ifstream in(path_);
  std::string line;
  while (std::getline(in, line))
    if (!line.empty()) lines.push_back(line);
  return lines;
}

}  // namespace autolink
