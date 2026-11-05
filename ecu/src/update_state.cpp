#include "autolink/update_state.hpp"

#include <map>
#include <set>

namespace autolink {

namespace {
using S = UpdateState;

const std::map<S, std::set<S>>& transitions() {
  static const std::map<S, std::set<S>> table = {
      {S::IDLE, {S::UPDATE_AVAILABLE}},
      {S::UPDATE_AVAILABLE, {S::DOWNLOADING, S::IDLE}},
      {S::DOWNLOADING, {S::VERIFYING, S::DOWNLOAD_FAILED}},
      {S::VERIFYING, {S::STAGING, S::VERIFICATION_FAILED}},
      {S::STAGING, {S::READY_TO_ACTIVATE, S::STAGING_FAILED}},
      {S::READY_TO_ACTIVATE, {S::ACTIVATING}},
      {S::ACTIVATING, {S::HEALTH_CHECK, S::ACTIVATION_FAILED}},
      {S::HEALTH_CHECK, {S::COMMITTED, S::ACTIVATION_FAILED}},
      {S::COMMITTED, {S::IDLE}},
      // Retry after a transient download failure, or give up.
      {S::DOWNLOAD_FAILED, {S::UPDATE_AVAILABLE, S::IDLE}},
      {S::VERIFICATION_FAILED, {S::IDLE}},
      {S::STAGING_FAILED, {S::IDLE}},
      {S::ACTIVATION_FAILED, {S::RECOVERY_IN_PROGRESS}},
      {S::RECOVERY_IN_PROGRESS, {S::ROLLED_BACK, S::RECOVERY_FAILED}},
      {S::ROLLED_BACK, {S::IDLE}},
      // Terminal: requires service intervention (`autolink-ecu --service-reset`).
      {S::RECOVERY_FAILED, {}},
  };
  return table;
}

const std::map<S, const char*>& names() {
  static const std::map<S, const char*> n = {
      {S::IDLE, "IDLE"},
      {S::UPDATE_AVAILABLE, "UPDATE_AVAILABLE"},
      {S::DOWNLOADING, "DOWNLOADING"},
      {S::VERIFYING, "VERIFYING"},
      {S::STAGING, "STAGING"},
      {S::READY_TO_ACTIVATE, "READY_TO_ACTIVATE"},
      {S::ACTIVATING, "ACTIVATING"},
      {S::HEALTH_CHECK, "HEALTH_CHECK"},
      {S::COMMITTED, "COMMITTED"},
      {S::DOWNLOAD_FAILED, "DOWNLOAD_FAILED"},
      {S::VERIFICATION_FAILED, "VERIFICATION_FAILED"},
      {S::STAGING_FAILED, "STAGING_FAILED"},
      {S::ACTIVATION_FAILED, "ACTIVATION_FAILED"},
      {S::RECOVERY_IN_PROGRESS, "RECOVERY_IN_PROGRESS"},
      {S::ROLLED_BACK, "ROLLED_BACK"},
      {S::RECOVERY_FAILED, "RECOVERY_FAILED"},
  };
  return n;
}
}  // namespace

const char* to_string(UpdateState s) { return names().at(s); }

std::optional<UpdateState> state_from_string(const std::string& s) {
  for (const auto& [state, name] : names())
    if (s == name) return state;
  return std::nullopt;
}

const std::vector<UpdateState>& all_states() {
  static const std::vector<UpdateState> v = [] {
    std::vector<UpdateState> out;
    for (const auto& [s, _] : names()) out.push_back(s);
    return out;
  }();
  return v;
}

bool is_valid_transition(UpdateState from, UpdateState to) {
  const auto& t = transitions();
  auto it = t.find(from);
  return it != t.end() && it->second.count(to) > 0;
}

bool is_quiescent(UpdateState s) { return s == S::IDLE || s == S::RECOVERY_FAILED; }

}  // namespace autolink
