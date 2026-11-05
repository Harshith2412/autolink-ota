# Requirements traceability matrix

Test IDs: `UT-` C++ unit tests (`ecu/tests/ecu_tests.cpp`), `BT-` backend tests (`backend/tests/test_api.py`),
`FT-` frontend unit tests (`frontend/tests/unit/rail.test.ts`), `IT-` integration tests (`tests/integration/`),
`EXP:` fault-injection scenarios (`experiments/scenarios/matrix.json`). Design columns point at the main module.

| Requirement | Design | Verification | Status |
|---|---|---|---|
| REQ-ECU-001 | `ecu/src/update_state.cpp` | UT001, UT003 | Verified |
| REQ-ECU-002 | `update_state.cpp`, `OtaAgent::transition` | UT002 | Verified |
| REQ-ECU-003 | transition table | UT004 | Verified |
| REQ-ECU-004 | `OtaAgent::service_reset` | UT054, EXP:recovery_failure | Verified |
| REQ-ECU-005 | `atomic_write_file`, `StateStore` | UT040, UT041, UT070–UT074 | Verified |
| REQ-ECU-006 | `OtaAgent::resume_after_boot` | UT070–UT074, IT004, EXP:power_loss_*, EXP:process_kill | Verified |
| REQ-ECU-007 | `EcuState` slots, `do_stage`, `do_activate` | UT050, UT053 | Verified |
| REQ-ECU-008 | `do_health_check`, `do_recovery` | UT053, EXP:health_check_failure, EXP:unhealthy_firmware | Verified |
| REQ-ECU-009 | `record_dtc` | UT051, UT052, BT024, IT002 | Verified |
| REQ-ECU-010 | `heartbeat_body` | BT029, IT001 | Verified |
| REQ-ECU-011 | outbox in `EcuState`, `flush_outbox` | UT059, EXP:backend_restart | Verified |
| REQ-SEC-001 | `crypto.cpp`, `security/manifest.py` | UT021, UT031, UT032, BT013, BT015, IT003, EXP:api_invalid_signature_upload, EXP:api_untrusted_key_upload | Verified |
| REQ-SEC-002 | `verify_image` | UT034, UT051, IT002, EXP:corrupted_artifact | Verified |
| REQ-SEC-003 | `TrustStore` | UT031, BT013, IT005, EXP:ecu_revoked_signing_key | Verified |
| REQ-SEC-004 | `verify_manifest`, `CampaignService.compatibility` | UT033, BT020, EXP:api_wrong_hardware_campaign | Verified |
| REQ-SEC-005 | `verify_manifest`, `min_security_counter` | UT033, UT053, UT060, BT021, EXP:api_rollback_campaign | Verified |
| REQ-SEC-006 | `OtaAgent::handle_commands`, `DeviceService.heartbeat` | UT055, UT056, BT024, BT028, EXP:duplicate_commands | Verified |
| REQ-SEC-007 | `kMaxFirmwareBytes`, `MAX_CONTENT_LENGTH` | UT033 (TOO_LARGE path not separately tested in ECU), BT013 (MALFORMED) | Partially verified |
| REQ-SEC-008 | `is_safe_identifier`, `LocalBlobStore` | UT035, BT010, BT013 | Verified |
| REQ-SEC-009 | `security/tokens.py`, `security/auth.py` | BT002–BT005 | Verified |
| REQ-SEC-010 | `require_device`, `_authorized_firmware` | BT011, BT025, BT026, BT027 | Verified |
| REQ-SEC-011 | `CampaignService.approve` | BT022 | Verified |
| REQ-SEC-012 | `AuditService` | BT001, BT013, IT010 (audit page) | Verified |
| REQ-SEC-013 | `.gitignore`, `scripts/dev_setup.py`, `Settings.from_env` | Manual review: repository contains only test-only fixture keys derived from public seeds | Reviewed |
| REQ-BE-001 | `backend/app/api/` | BT010–BT041, IT001 | Verified |
| REQ-BE-002 | `CampaignService.compatibility` | BT020, BT021 | Verified |
| REQ-BE-003 | `deployment_events` unique key | BT024, UT059 | Verified |
| REQ-BE-004 | `DeviceService._apply` | BT024 (mutation-checked) | Verified |
| REQ-BE-005 | migration 0002, `apply_state_event` | EXP:packet_loss (defect found and fixed, see fault-injection report) | Verified |
| REQ-BE-006 | `validation.py`, `errors.py` | BT016, BT041 | Verified |
| REQ-BE-007 | `Database.migrate` | every backend test applies 0001–0002 on a fresh DB | Verified |
| REQ-BE-008 | `_clean_telemetry` | BT029 | Verified |
| REQ-UI-001 | `frontend/src/pages/` | IT010 | Verified |
| REQ-UI-002 | `can.*` in `services/api.ts` | IT010 (admin views); viewer-role UI not browser-tested | Partially verified |
| REQ-UI-003 | `LifecycleRail.tsx` | FT (8 cases), IT010 | Verified |
| REQ-UI-004 | `Loaded`, `Confirm` in `components/ui.tsx` | IT010 (error state on bad login); empty states and dialogs not browser-tested | Partially verified |
| REQ-UI-005 | `styles.css` | IT010 (labels, headings, skip link, 390 px and 1360 px overflow) | Verified |
| REQ-REL-001 | ECU retry/backoff, Range resume | EXP: interrupted_download, network_delay, packet_loss, truncated_responses, network_disconnection, backend_restart | Verified |
| REQ-REL-002 | whole system | consistency checks on every EXP execution | Verified |
