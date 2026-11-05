// Unit and component tests for the ECU simulator. Test IDs (UT-xxx) are
// referenced from docs/requirements/traceability.md.
#include <ftw.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cstdlib>
#include <fstream>
#include <map>
#include <sstream>

#include "autolink/crypto.hpp"
#include "autolink/ecu_state.hpp"
#include "autolink/manifest.hpp"
#include "autolink/ota_agent.hpp"
#include "autolink/update_state.hpp"
#include "test_framework.hpp"

#ifndef AUTOLINK_FIXTURE_DIR
#define AUTOLINK_FIXTURE_DIR "ecu/tests/fixtures"
#endif

using namespace autolink;

namespace {
const char* kHw = "ALK-TCU-R1";
const char* kVin = "VIN-TEST-0001";

std::string slurp(const std::string& p) {
  std::ifstream in(p, std::ios::binary);
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}
std::string fixture(const std::string& name) { return std::string(AUTOLINK_FIXTURE_DIR) + "/" + name; }

class TempDir {
 public:
  TempDir() {
    char tmpl[] = "/tmp/autolink-test-XXXXXX";
    path_ = ::mkdtemp(tmpl);
  }
  ~TempDir() {
    ::nftw(path_.c_str(), [](const char* p, const struct stat*, int, struct FTW*) { return ::remove(p); }, 16,
           FTW_DEPTH | FTW_PHYS);
  }
  const std::string& path() const { return path_; }

 private:
  std::string path_;
};

TrustStore test_trust() { return TrustStore::from_json(json::parse(slurp(fixture("trust.json")))); }

struct FakeCloud : CloudLink {
  std::map<std::string, std::pair<std::string, std::string>> firmware;  // id -> (manifest, image)
  std::vector<Command> commands;
  std::vector<json::Value> events;
  bool offline = false;
  int fail_next_downloads = 0;
  int64_t truncate_download_at = -1;  // emulate connection drop mid-transfer
  int64_t last_range_offset = -1;

  void add(const std::string& name) {
    std::string manifest = slurp(fixture(name + ".manifest.json"));
    auto id = json::parse(manifest).str("firmware_id");
    firmware[id] = {manifest, slurp(fixture(name + ".img"))};
  }
  std::string id_of(const std::string& name) {
    return json::parse(slurp(fixture(name + ".manifest.json"))).str("firmware_id");
  }
  void queue_install(int64_t seq, const std::string& fw_id, int64_t expires = 4102444800 /*2100*/) {
    Command c;
    c.seq = seq;
    c.type = "install";
    c.vehicle_id = kVin;
    c.deployment_id = "dep-" + std::to_string(seq);
    c.firmware_id = fw_id;
    c.expires_at = expires;
    commands.push_back(c);
  }
  std::vector<Command> heartbeat(const json::Value& body) override {
    if (offline) throw TransportError("offline");
    std::vector<Command> out;
    for (auto& c : commands)
      if (c.seq > body.integer("last_command_seq")) out.push_back(c);
    return out;
  }
  json::Value fetch_manifest(const std::string& id) override {
    if (offline) throw TransportError("offline");
    auto it = firmware.find(id);
    if (it == firmware.end()) throw TransportError("404");
    return json::parse(it->second.first);
  }
  void download(const std::string& id, const std::string& dest, int64_t offset, int64_t max_total,
                const std::function<bool(int64_t)>& on_progress) override {
    if (offline) throw TransportError("offline");
    if (fail_next_downloads > 0) {
      --fail_next_downloads;
      throw TransportError("injected download failure");
    }
    last_range_offset = offset;
    const std::string& img = firmware.at(id).second;
    std::ofstream out(dest, std::ios::binary | std::ios::app);
    int64_t total = offset;
    const int64_t chunk = 512;
    for (int64_t i = offset; i < static_cast<int64_t>(img.size()); i += chunk) {
      int64_t n = std::min<int64_t>(chunk, static_cast<int64_t>(img.size()) - i);
      if (total + n > max_total) throw TransportError("too large");
      if (truncate_download_at >= 0 && total + n > truncate_download_at) {
        truncate_download_at = -1;
        throw TransportError("connection dropped");
      }
      out.write(img.data() + i, n);
      out.flush();
      total += n;
      if (!on_progress(total)) throw TransportError("aborted");
    }
  }
  void post_events(const std::vector<std::string>& evs) override {
    if (offline) throw TransportError("offline");
    for (const auto& e : evs) events.push_back(json::parse(e));
  }
  bool saw_state(const std::string& s) const {
    for (const auto& e : events)
      if (e.str("kind") == "STATE" && e.str("to_state") == s) return true;
    return false;
  }
  bool saw_dtc(const std::string& code) const {
    for (const auto& e : events)
      if (e.str("kind") == "DTC" && e.str("code") == code) return true;
    return false;
  }
};

AgentConfig cfg_for(const TempDir& d) {
  AgentConfig c;
  c.state_dir = d.path();
  c.vehicle_id = kVin;
  c.ecu_id = "ECU-TCU-01";
  c.hardware_id = kHw;
  c.factory_version = "1.0.0";
  c.backoff_base_ms = 1;
  return c;
}

OtaAgent make_agent(const TempDir& d, FakeCloud& cloud, FaultConfig f = {}) {
  return OtaAgent(cfg_for(d), cloud, test_trust(), f, [] { return int64_t{1800000000}; }, [](int) {});
}
}  // namespace

// ---------------------------------------------------------------- state machine
TEST(StateMachine, UT001_HappyPathTransitionsAreValid) {
  using S = UpdateState;
  const S path[] = {S::IDLE, S::UPDATE_AVAILABLE, S::DOWNLOADING, S::VERIFYING, S::STAGING,
                    S::READY_TO_ACTIVATE, S::ACTIVATING, S::HEALTH_CHECK, S::COMMITTED, S::IDLE};
  for (size_t i = 0; i + 1 < sizeof(path) / sizeof(path[0]); ++i)
    EXPECT_TRUE(is_valid_transition(path[i], path[i + 1]));
}

TEST(StateMachine, UT002_InvalidTransitionsRejected) {
  using S = UpdateState;
  EXPECT_FALSE(is_valid_transition(S::IDLE, S::ACTIVATING));
  EXPECT_FALSE(is_valid_transition(S::DOWNLOADING, S::STAGING));       // verification cannot be skipped
  EXPECT_FALSE(is_valid_transition(S::VERIFICATION_FAILED, S::STAGING));
  EXPECT_FALSE(is_valid_transition(S::RECOVERY_FAILED, S::IDLE));      // terminal latch
  EXPECT_FALSE(is_valid_transition(S::COMMITTED, S::ROLLED_BACK));
  EXPECT_FALSE(is_valid_transition(S::IDLE, S::IDLE));
}

TEST(StateMachine, UT003_EveryStateNameRoundTrips) {
  for (auto s : all_states()) {
    auto back = state_from_string(to_string(s));
    ASSERT_TRUE(back.has_value());
    EXPECT_TRUE(*back == s);
  }
  EXPECT_FALSE(state_from_string("BOGUS").has_value());
  EXPECT_EQ(all_states().size(), size_t{16});
}

TEST(StateMachine, UT004_NoStateSkipsVerificationToReachStaging) {
  for (auto s : all_states())
    if (is_valid_transition(s, UpdateState::STAGING)) EXPECT_TRUE(s == UpdateState::VERIFYING);
}

// ---------------------------------------------------------------- versions
TEST(Version, UT010_ParseAndCompare) {
  auto a = SemVer::parse("1.2.3"), b = SemVer::parse("1.10.0");
  ASSERT_TRUE(a && b);
  EXPECT_EQ(a->compare(*b), -1);
  EXPECT_EQ(b->compare(*a), 1);
  EXPECT_EQ(a->compare(*SemVer::parse("1.2.3")), 0);
  EXPECT_FALSE(SemVer::parse("1.2").has_value());
  EXPECT_FALSE(SemVer::parse("01.2.3").has_value());
  EXPECT_FALSE(SemVer::parse("1.2.3-rc1").has_value());
  EXPECT_FALSE(SemVer::parse("../1.2.3").has_value());
}

// ---------------------------------------------------------------- crypto
TEST(Crypto, UT020_Sha256KnownAnswer) {
  EXPECT_EQ(crypto::sha256_hex(std::string("abc")),
            std::string("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
}

TEST(Crypto, UT021_Ed25519Rfc8032Vector1) {
  crypto::Bytes pk, sig;
  ASSERT_TRUE(crypto::hex_decode("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", pk));
  ASSERT_TRUE(crypto::hex_decode(
      "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
      sig));
  EXPECT_TRUE(crypto::ed25519_verify(pk, sig, ""));
  EXPECT_FALSE(crypto::ed25519_verify(pk, sig, "x"));
  sig[0] ^= 1;
  EXPECT_FALSE(crypto::ed25519_verify(pk, sig, ""));
  EXPECT_FALSE(crypto::ed25519_verify(crypto::Bytes(31), sig, ""));
}

TEST(Crypto, UT022_StrictDecoders) {
  crypto::Bytes out;
  EXPECT_TRUE(crypto::base64_decode("aGVsbG8=", out));
  EXPECT_EQ(std::string(out.begin(), out.end()), std::string("hello"));
  EXPECT_FALSE(crypto::base64_decode("aGVsbG8", out));
  EXPECT_FALSE(crypto::base64_decode("aGV*bG8=", out));
  EXPECT_FALSE(crypto::base64_decode("a=Vs", out));
  EXPECT_FALSE(crypto::hex_decode("abc", out));
  EXPECT_FALSE(crypto::hex_decode("zz", out));
}

// ---------------------------------------------------------------- manifest policy
namespace {
VerifyResult verify_fixture(const std::string& name, const std::string& current = "1.0.0", int64_t floor = 0) {
  auto m = FirmwareManifest::from_json(json::parse(slurp(fixture(name + ".manifest.json"))));
  auto r = verify_manifest(m, test_trust(), {kHw, current, floor});
  if (r.ok()) r = verify_image(m, fixture(name + ".img"));
  return r;
}
}  // namespace

TEST(Manifest, UT030_ValidSignedPackageAccepted) { EXPECT_TRUE(verify_fixture("v110").ok()); }

TEST(Manifest, UT031_SignatureFailures) {
  EXPECT_TRUE(verify_fixture("untrusted_key").error == VerifyError::BAD_SIGNATURE);
  EXPECT_TRUE(verify_fixture("unknown_key").error == VerifyError::UNKNOWN_KEY);
  EXPECT_TRUE(verify_fixture("revoked_key").error == VerifyError::REVOKED_KEY);
}

TEST(Manifest, UT032_TamperedFieldInvalidatesSignature) {
  auto v = json::parse(slurp(fixture("v110.manifest.json")));
  auto m = FirmwareManifest::from_json(v);
  m.hardware_id = kHw;
  m.version = "9.9.9";  // attacker bumps version but cannot re-sign
  EXPECT_TRUE(verify_manifest(m, test_trust(), {kHw, "1.0.0", 0}).error == VerifyError::BAD_SIGNATURE);
  m = FirmwareManifest::from_json(v);
  m.simulate_unhealthy = true;
  EXPECT_TRUE(verify_manifest(m, test_trust(), {kHw, "1.0.0", 0}).error == VerifyError::BAD_SIGNATURE);
}

TEST(Manifest, UT033_PolicyChecks) {
  EXPECT_TRUE(verify_fixture("wrong_hw").error == VerifyError::WRONG_HARDWARE);
  EXPECT_TRUE(verify_fixture("v090_old").error == VerifyError::ROLLBACK);
  EXPECT_TRUE(verify_fixture("v110", "1.1.0").error == VerifyError::ROLLBACK);  // same version
  EXPECT_TRUE(verify_fixture("v300_counter3", "2.0.0", 5).error == VerifyError::ROLLBACK);
  EXPECT_TRUE(verify_fixture("needs_150").error == VerifyError::INCOMPATIBLE_VERSION);
}

TEST(Manifest, UT034_CorruptedImageRejected) {
  TempDir d;
  std::string img = slurp(fixture("v110.img"));
  img[img.size() / 2] ^= 0x01;
  std::ofstream(d.path() + "/x.img", std::ios::binary) << img;
  auto m = FirmwareManifest::from_json(json::parse(slurp(fixture("v110.manifest.json"))));
  EXPECT_TRUE(verify_image(m, d.path() + "/x.img").error == VerifyError::DIGEST_MISMATCH);
  std::ofstream(d.path() + "/y.img", std::ios::binary) << img.substr(0, 10);
  EXPECT_TRUE(verify_image(m, d.path() + "/y.img").error == VerifyError::SIZE_MISMATCH);
}

TEST(Manifest, UT035_UnsafeIdentifiersRejected) {
  EXPECT_FALSE(is_safe_identifier("../../etc/passwd"));
  EXPECT_FALSE(is_safe_identifier("fw/1"));
  EXPECT_FALSE(is_safe_identifier("a..b"));
  EXPECT_FALSE(is_safe_identifier(""));
  EXPECT_TRUE(is_safe_identifier("fw-v110"));
}

// ---------------------------------------------------------------- persistence
TEST(Persistence, UT040_StateRoundTripsAtomically) {
  TempDir d;
  StateStore store(d.path() + "/state.json");
  EcuState s;
  s.vehicle_id = kVin;
  s.ecu_id = "E";
  s.hardware_id = kHw;
  s.update_state = UpdateState::STAGING;
  s.active_slot = 'B';
  s.min_security_counter = 7;
  s.outbox.push_back("{\"a\":1}");
  s.dtcs.push_back({"U3001", "ERROR", "x", "dep", 5});
  store.save(s);
  auto t = store.load();
  EXPECT_TRUE(t.update_state == UpdateState::STAGING);
  EXPECT_EQ(t.active_slot, 'B');
  EXPECT_EQ(t.min_security_counter, int64_t{7});
  EXPECT_EQ(t.outbox.size(), size_t{1});
  EXPECT_EQ(t.dtcs.at(0).code, std::string("U3001"));
  EXPECT_NE(::access((d.path() + "/state.json.tmp").c_str(), F_OK), 0);  // no leftover temp
}

TEST(Persistence, UT041_CorruptStateFailsClosed) {
  TempDir d;
  std::ofstream(d.path() + "/state.json") << "{\"schema_version\":1,\"update_state\":\"NOPE\"}";
  EXPECT_THROW(StateStore(d.path() + "/state.json").load(), std::runtime_error);
}

// ---------------------------------------------------------------- agent
TEST(Agent, UT050_SuccessfulUpdateCommits) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  auto agent = make_agent(d, cloud);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("v110"));
  ASSERT_TRUE(agent.cycle());
  const auto& s = agent.state();
  EXPECT_TRUE(s.update_state == UpdateState::IDLE);
  EXPECT_EQ(s.active().version, std::string("1.1.0"));
  EXPECT_EQ(s.active_slot, 'B');
  EXPECT_EQ(s.last_known_good_slot, 'B');
  EXPECT_EQ(s.min_security_counter, int64_t{1});
  EXPECT_TRUE(cloud.saw_state("COMMITTED"));
  EXPECT_TRUE(s.outbox.empty());
  // Journal recorded every transition.
  EXPECT_GT(Journal(d.path() + "/journal.log").read_all().size(), size_t{9});
}

TEST(Agent, UT051_CorruptedDownloadRejectedNotActivated) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  FaultConfig f;
  f.corrupt_downloaded_image = true;
  auto agent = make_agent(d, cloud, f);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("v110"));
  agent.cycle();
  EXPECT_TRUE(cloud.saw_state("VERIFICATION_FAILED"));
  EXPECT_FALSE(cloud.saw_state("STAGING"));
  EXPECT_TRUE(cloud.saw_dtc("U3002"));
  EXPECT_EQ(agent.state().active().version, std::string("1.0.0"));
  EXPECT_EQ(agent.state().active_slot, 'A');
}

TEST(Agent, UT052_InvalidSignatureRejected) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("untrusted_key");
  auto agent = make_agent(d, cloud);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("untrusted_key"));
  agent.cycle();
  EXPECT_TRUE(cloud.saw_dtc("U3001"));
  EXPECT_EQ(agent.state().active().version, std::string("1.0.0"));
  EXPECT_EQ(agent.state().counters.verification_failures, int64_t{1});
}

TEST(Agent, UT053_HealthCheckFailureRollsBack) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("unhealthy");
  auto agent = make_agent(d, cloud);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("unhealthy"));
  agent.cycle();
  const auto& s = agent.state();
  EXPECT_TRUE(cloud.saw_state("ROLLED_BACK"));
  EXPECT_EQ(s.active_slot, 'A');
  EXPECT_EQ(s.active().version, std::string("1.0.0"));
  EXPECT_EQ(s.min_security_counter, int64_t{0});  // floor not raised by a failed update
  EXPECT_EQ(s.counters.rollbacks, int64_t{1});
}

TEST(Agent, UT054_RecoveryFailureLatches) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  FaultConfig f;
  f.health_check_fail = true;
  f.recovery_fail = true;
  auto agent = make_agent(d, cloud, f);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("v110"));
  agent.cycle();
  EXPECT_TRUE(agent.state().update_state == UpdateState::RECOVERY_FAILED);
  EXPECT_TRUE(cloud.saw_dtc("U3040"));
  agent.service_reset();
  EXPECT_TRUE(agent.state().update_state == UpdateState::IDLE);
}

TEST(Agent, UT055_DuplicateAndOutOfOrderCommandsIgnored) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  cloud.add("v120");
  FaultConfig f;
  f.replay_commands = true;
  auto agent = make_agent(d, cloud, f);
  agent.boot();
  cloud.queue_install(5, cloud.id_of("v110"));
  agent.cycle();
  EXPECT_EQ(agent.state().counters.updates_attempted, int64_t{1});
  EXPECT_EQ(agent.state().counters.duplicate_commands, int64_t{1});
  // An older command (seq 3) arriving late must not execute.
  agent.handle_commands({[&] {
    Command c;
    c.seq = 3;
    c.type = "install";
    c.vehicle_id = kVin;
    c.deployment_id = "dep-old";
    c.firmware_id = cloud.id_of("v120");
    c.expires_at = 4102444800;
    return c;
  }()});
  EXPECT_EQ(agent.state().counters.updates_attempted, int64_t{1});
  EXPECT_EQ(agent.state().active().version, std::string("1.1.0"));
}

TEST(Agent, UT056_ExpiredOrMisaddressedCommandsRejected) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  auto agent = make_agent(d, cloud);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("v110"), /*expires=*/1000);
  Command other;
  other.seq = 2;
  other.type = "install";
  other.vehicle_id = "VIN-SOMEONE-ELSE";
  other.deployment_id = "dep-2";
  other.firmware_id = cloud.id_of("v110");
  other.expires_at = 4102444800;
  cloud.commands.push_back(other);
  agent.cycle();
  EXPECT_EQ(agent.state().counters.commands_rejected, int64_t{2});
  EXPECT_EQ(agent.state().active().version, std::string("1.0.0"));
}

TEST(Agent, UT057_InterruptedDownloadResumesWithRange) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  cloud.truncate_download_at = 2048;
  auto agent = make_agent(d, cloud);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("v110"));
  agent.cycle();
  EXPECT_TRUE(cloud.saw_state("DOWNLOAD_FAILED"));
  EXPECT_EQ(cloud.last_range_offset, int64_t{2048});
  EXPECT_EQ(agent.state().active().version, std::string("1.1.0"));
  EXPECT_EQ(agent.state().counters.download_retries, int64_t{1});
}

TEST(Agent, UT058_DownloadAbandonedAfterMaxAttempts) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  cloud.fail_next_downloads = 100;
  auto agent = make_agent(d, cloud);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("v110"));
  agent.cycle();
  EXPECT_TRUE(agent.state().update_state == UpdateState::IDLE);
  EXPECT_TRUE(cloud.saw_dtc("U3011"));
  EXPECT_EQ(agent.state().active().version, std::string("1.0.0"));
}

TEST(Agent, UT059_EventsQueuedWhileOfflineAndFlushedLater) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  auto agent = make_agent(d, cloud);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("v110"));
  auto cmds = cloud.heartbeat(json::Object{{"last_command_seq", 0}});
  cloud.offline = true;
  agent.handle_commands(cmds);
  agent.run_update();  // download fails offline -> abandoned
  EXPECT_GT(agent.state().outbox.size(), size_t{0});
  cloud.offline = false;
  EXPECT_TRUE(agent.flush_outbox());
  EXPECT_TRUE(agent.state().outbox.empty());
  // event_seq strictly increasing => backend can de-duplicate replays
  int64_t prev = 0;
  for (const auto& e : cloud.events) {
    EXPECT_GT(e.integer("event_seq"), prev);
    prev = e.integer("event_seq");
  }
}

TEST(Agent, UT060_AntiRollbackFloorPersistsAcrossUpdates) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v200_counter5");
  cloud.add("v300_counter3");
  auto agent = make_agent(d, cloud);
  agent.boot();
  cloud.queue_install(1, cloud.id_of("v200_counter5"));
  agent.cycle();
  EXPECT_EQ(agent.state().min_security_counter, int64_t{5});
  cloud.queue_install(2, cloud.id_of("v300_counter3"));  // newer version, revoked counter
  agent.cycle();
  EXPECT_EQ(agent.state().active().version, std::string("2.0.0"));
  EXPECT_TRUE(cloud.saw_dtc("U3004"));
}

// Simulated power loss: fork a child that crashes right after persisting the
// given state, then boot a fresh agent on the same storage.
namespace {
EcuState crash_and_reboot(UpdateState crash_state, FakeCloud& cloud, const TempDir& d) {
  std::cout.flush();
  std::cerr.flush();
  pid_t pid = ::fork();
  if (pid == 0) {
    FaultConfig f;
    f.crash_after_entering = crash_state;
    auto agent = make_agent(d, cloud, f);
    agent.boot();
    cloud.queue_install(1, cloud.id_of("v110"));
    agent.cycle();
    std::_Exit(0);  // should not reach
  }
  int status = 0;
  ::waitpid(pid, &status, 0);
  EXPECT_TRUE(WIFEXITED(status) && WEXITSTATUS(status) == kPowerLossExitCode);
  StateStore store(d.path() + "/state.json");
  EXPECT_TRUE(store.load().update_state == crash_state);
  cloud.queue_install(1, cloud.id_of("v110"));
  auto agent = make_agent(d, cloud);
  agent.boot();
  agent.cycle();
  return agent.state();
}
}  // namespace

TEST(PowerLoss, UT070_DuringDownloadResumesAndCommits) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  auto s = crash_and_reboot(UpdateState::DOWNLOADING, cloud, d);
  EXPECT_EQ(s.active().version, std::string("1.1.0"));
  EXPECT_TRUE(s.update_state == UpdateState::IDLE);
}

TEST(PowerLoss, UT071_DuringStagingRestagesAndCommits) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  auto s = crash_and_reboot(UpdateState::STAGING, cloud, d);
  EXPECT_EQ(s.active().version, std::string("1.1.0"));
}

TEST(PowerLoss, UT072_DuringActivationRollsBackToKnownGood) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  auto s = crash_and_reboot(UpdateState::ACTIVATING, cloud, d);
  EXPECT_EQ(s.active().version, std::string("1.0.0"));
  EXPECT_EQ(s.active_slot, 'A');
  EXPECT_EQ(s.counters.rollbacks, int64_t{1});
  EXPECT_EQ(s.counters.updates_attempted, int64_t{1});  // seq 1 not re-executed after reboot
}

TEST(PowerLoss, UT073_DuringHealthCheckRollsBack) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  auto s = crash_and_reboot(UpdateState::HEALTH_CHECK, cloud, d);
  EXPECT_EQ(s.active().version, std::string("1.0.0"));
}

TEST(PowerLoss, UT074_AfterCommitStaysOnNewVersion) {
  TempDir d;
  FakeCloud cloud;
  cloud.add("v110");
  auto s = crash_and_reboot(UpdateState::COMMITTED, cloud, d);
  EXPECT_EQ(s.active().version, std::string("1.1.0"));
  EXPECT_EQ(s.counters.rollbacks, int64_t{0});
}

#if !AUTOLINK_USING_GTEST
int main() { return minitest::run_all(); }
#endif
