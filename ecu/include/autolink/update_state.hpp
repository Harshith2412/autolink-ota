// OTA update state machine (REQ-ECU-001..004). The transition table is the
// single source of truth; see docs/architecture/ota-state-machine.md.
#pragma once

#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace autolink {

enum class UpdateState {
  IDLE,
  UPDATE_AVAILABLE,
  DOWNLOADING,
  VERIFYING,
  STAGING,
  READY_TO_ACTIVATE,
  ACTIVATING,
  HEALTH_CHECK,
  COMMITTED,
  DOWNLOAD_FAILED,
  VERIFICATION_FAILED,
  STAGING_FAILED,
  ACTIVATION_FAILED,
  RECOVERY_IN_PROGRESS,
  ROLLED_BACK,
  RECOVERY_FAILED,
};

const char* to_string(UpdateState s);
std::optional<UpdateState> state_from_string(const std::string& s);
const std::vector<UpdateState>& all_states();

bool is_valid_transition(UpdateState from, UpdateState to);
// True for states from which the ECU is not in the middle of an update.
bool is_quiescent(UpdateState s);

class InvalidTransition : public std::logic_error {
 public:
  InvalidTransition(UpdateState from, UpdateState to)
      : std::logic_error(std::string("invalid update-state transition ") + to_string(from) +
                         " -> " + to_string(to)) {}
};

}  // namespace autolink
