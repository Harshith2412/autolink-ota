# Threat model

Method: STRIDE per element across the trust boundaries in `docs/architecture/overview.md` (B1 operator↔cloud,
B2 cloud internals, B3 vehicle). Evidence refers to automated tests (UT/BT/IT) or experiment scenarios (EXP).
"Residual" states what remains after the mitigation. Nothing here is claimed as fully mitigated without evidence,
and the prototype runs without TLS locally (T-11), which weakens several network-facing items.

| ID | STRIDE | Threat | Status |
|---|---|---|---|
| T-01 | Tampering | Compromised firmware repository or blob store | Mitigated on ECU |
| T-02 | Tampering, EoP | Malicious firmware upload | Mitigated |
| T-03 | EoP | Unauthorized deployment | Mitigated |
| T-04 | Tampering | Firmware rollback / downgrade | Partially mitigated |
| T-05 | Spoofing, Tampering | Message replay | Mitigated |
| T-06 | Spoofing | MQTT credential compromise | Not applicable yet (MQTT not implemented) |
| T-07 | Spoofing | Vehicle impersonation | Partially mitigated |
| T-08 | EoP | API authorization bypass | Mitigated |
| T-09 | Info disclosure, Tampering | Database compromise | Partially mitigated |
| T-10 | Tampering, Repudiation | Telemetry manipulation | Partially mitigated |
| T-11 | Info disclosure, Tampering | Network interception (no TLS in local stack) | Open in local stack |
| T-12 | DoS | Denial of service | Partially mitigated |
| T-13 | Info disclosure | Cloud credential leakage | Partially mitigated |
| T-14 | Spoofing, Tampering | Signing-key compromise | Not prevented; revocation only |
| T-15 | DoS, Tampering | Update interruption | Mitigated (simulated) |

### T-01 Compromised firmware repository
- **Asset / boundary:** firmware images and manifests; B2→B3.
- **Precondition:** attacker can modify blobs, manifests or database rows on the backend.
- **Impact:** malicious or corrupted image delivered to vehicles.
- **Mitigation:** the ECU verifies the Ed25519 signature with its own trust store and the SHA-256 and size of the
  downloaded bytes before staging; the backend is not trusted for authenticity. Blobs are content-addressed.
- **Evidence:** UT031, UT032, UT034, UT051, IT002, EXP:corrupted_artifact (7/7 rejected), EXP:ecu_revoked_signing_key.
- **Residual:** an attacker can still withhold updates or replay an *older validly signed* image subject to T-04.

### T-02 Malicious firmware upload
- **Asset / boundary:** fleet integrity; B1→B2.
- **Precondition:** stolen engineer credentials, or an insider.
- **Impact:** an unsigned or tampered package enters the catalogue.
- **Mitigation:** upload requires engineer role; the backend rejects bad signatures, unknown/revoked keys, digest
  mismatches, malformed or oversized manifests; every rejection is audited.
- **Evidence:** BT013, BT014, IT003, EXP:api_invalid_signature_upload, EXP:api_untrusted_key_upload (7/7 each).
- **Residual:** a validly signed but harmful image is out of scope for signature checks; that is a release-process
  control (code review, signing ceremony).

### T-03 Unauthorized deployment
- **Asset / boundary:** campaign approval; B1.
- **Precondition:** one compromised account.
- **Impact:** firmware pushed to vehicles without sanction.
- **Mitigation:** campaigns are drafted by engineers and approved by an admin who is not the creator; no command
  exists before approval; approval re-checks compatibility; audited.
- **Evidence:** BT022, BT023, BT004.
- **Residual:** two colluding or compromised admins. Self-approval can be enabled by configuration for single-user
  demos (`AUTOLINK_ALLOW_SELF_APPROVAL`), default off.

### T-04 Firmware rollback
- **Asset / boundary:** security fixes on the vehicle; B3.
- **Precondition:** attacker can deliver an old, validly signed image.
- **Impact:** reintroduces a patched vulnerability.
- **Mitigation:** ECU rejects versions not newer than installed and security counters below a persisted floor that
  rises only on commit; backend rejects downgrade campaigns.
- **Evidence:** UT033, UT060, UT053, BT021, EXP:api_rollback_campaign.
- **Residual:** the floor is stored in a writable file on the simulator. Real hardware needs OTP fuses or RPMB.

### T-05 Message replay
- **Asset / boundary:** install commands and events; B2↔B3.
- **Precondition:** attacker or flaky network re-delivers old messages.
- **Impact:** repeated installs, or status regression in the cloud.
- **Mitigation:** per-vehicle monotonic command `seq` with expiry and vehicle binding; ECU advances
  `last_command_seq` even on rejection; backend deduplicates events by `(vehicle_id, event_seq)` and never regresses
  terminal statuses.
- **Evidence:** UT055, UT056, BT024, BT028, EXP:duplicate_commands (7/7).
- **Residual:** commands are authenticated only by the transport (device token + TLS in deployment), not signed
  end-to-end. A compromised backend can issue new, validly sequenced commands, but still only for signed firmware.

### T-06 MQTT credential compromise
- Not implemented, so not applicable. The planned design (per-vehicle certificates, topic ACLs, TLS) is in
  `docs/api/vehicle-protocol.md`.

### T-07 Vehicle impersonation
- **Asset / boundary:** fleet records and firmware access; B3→B2.
- **Precondition:** attacker holds or guesses a device token.
- **Impact:** false telemetry or status; reading firmware intended for that vehicle.
- **Mitigation:** 256-bit random tokens, stored as SHA-256, compared in constant time; payload vehicle id must
  match; a vehicle can fetch only firmware targeted at it; token rotation endpoint; failures audited.
- **Evidence:** BT011, BT025, BT026, BT027.
- **Residual:** bearer tokens can be extracted from a compromised ECU. Production should use per-device keys in a
  secure element with mutual TLS.

### T-08 API authorization bypass
- **Asset / boundary:** management API; B1.
- **Precondition:** forged, expired or alg-confused tokens; lower-privileged user.
- **Impact:** privilege escalation.
- **Mitigation:** algorithm pinned to HS256, audience/issuer/expiry required, role re-read from the database, role
  checks on every route, separate device authentication.
- **Evidence:** BT002 (tampered, `alg=none`, wrong key), BT003, BT004, BT005.
- **Residual:** no token revocation list; a stolen token works for up to its 15-minute lifetime unless the user is
  disabled.

### T-09 Database compromise
- **Asset / boundary:** credentials and records; B2.
- **Precondition:** read or write access to the database file.
- **Impact:** disclosure or tampering of fleet records.
- **Mitigation:** passwords as PBKDF2-SHA256 (600k iterations default), device tokens hashed, no signing keys in
  the database; ECU does not trust database content for authenticity.
- **Evidence:** BT011; design review.
- **Residual:** database tampering can falsify history and the audit log (no hash chaining). No encryption at rest
  for SQLite.

### T-10 Telemetry manipulation
- **Asset / boundary:** telemetry and diagnostics; B3→B2.
- **Precondition:** a malicious or faulty vehicle.
- **Impact:** misleading fleet view.
- **Mitigation:** authentication, identity binding, range validation with a C0002 diagnostic for discarded values.
- **Evidence:** BT029, BT025.
- **Residual:** an authenticated vehicle can still report plausible false values; telemetry is not signed.

### T-11 Network interception
- **Asset / boundary:** tokens and commands in transit; B1, B2↔B3.
- **Precondition:** network access between parties.
- **Impact:** credential theft, command injection (not firmware injection, see T-01).
- **Mitigation:** none in the local stack (HTTP on loopback). Deployment requires a TLS-terminating proxy and an
  HTTPS client on the ECU (`CloudLink` seam). The S3 bucket policy in Terraform denies non-TLS access.
- **Evidence:** none for TLS; this is an open item.
- **Residual:** high until TLS is implemented.

### T-12 Denial of service
- **Asset / boundary:** backend availability; all boundaries.
- **Mitigation:** request and image size limits, event batches capped at 256, bounded ECU outbox and DTC list,
  pagination caps, ECU exponential backoff with jitter.
- **Evidence:** BT031; EXP:backend_restart and EXP:network_disconnection show recovery after outages.
- **Residual:** no rate limiting or login throttling; the Flask development server is single-process.

### T-13 Cloud credential leakage
- **Mitigation:** no secrets in the repository; configuration from environment; `.dev/` git-ignored with 0600
  files; Terraform IAM policy limited to the firmware prefix and one log group.
- **Evidence:** repository review; `Settings.from_env` refuses short JWT secrets and wildcard CORS.
- **Residual:** no secrets manager integration; the Terraform was not applied.

### T-14 Signing-key compromise
- **Impact:** attacker can produce firmware every ECU accepts.
- **Mitigation:** key ids with revocation lists in both trust stores; development keys generated per checkout and
  labelled; production guidance: HSM/KMS, offline signing, threshold approval.
- **Evidence:** UT031 (revoked key), IT005, EXP:ecu_revoked_signing_key.
- **Residual:** revocation requires distributing an updated trust store, which is not implemented (it would itself
  need to be a signed update). This is the largest structural gap.

### T-15 Update interruption
- **Mitigation:** atomic persistence, A/B slots, resume with Range, unconfirmed-boot rollback.
- **Evidence:** UT057, UT070–UT074, IT004, all EXP power-loss, kill and network scenarios (175/175 consistent).
- **Residual:** simulated storage only; real flash partial-write behaviour and bootloader cooperation are untested.
