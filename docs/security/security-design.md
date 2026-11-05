# Security design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Firmware signatures | Ed25519 via OpenSSL (ECU) and `cryptography` (cloud, tooling) | Small keys and signatures, deterministic, no parameter choices to get wrong. No custom cryptography. |
| What is signed | Canonical manifest payload (below), not the JSON text | JSON has no canonical form; a fixed, length-prefixed field list means the C++ and Python verifiers agree byte-for-byte (BT015). |
| Image integrity | SHA-256 of the image inside the signed manifest | One signature covers metadata and content; the digest check happens before staging and again after staging. |
| Root of trust | ECU trust store | The backend also verifies, but compromise of the backend must not let firmware onto vehicles. |
| Anti-rollback | Version ordering plus monotonic security counter, floor raised on commit | Counter lets a release revoke vulnerable versions without changing semantic versions; raising only on commit avoids bricking on a failed update. |
| Command replay | Per-vehicle sequence, expiry, vehicle binding | Simple, stateful, testable; consumed even when rejected. |
| User auth | HS256 JWT, 15 min, role re-read from DB | Short-lived and verifiable; the database remains the authority for roles. |
| Device auth | Random bearer token, SHA-256 at rest | Adequate for a prototype; production would use mTLS with keys in a secure element. |
| Passwords | PBKDF2-HMAC-SHA256, 600,000 iterations, per-user salt | Standard library only; OWASP-recommended iteration count for PBKDF2-SHA256. |
| Separation of duties | Creator cannot approve | Two-person rule for fleet-wide action. |
| Storage keys | Content-addressed (SHA-256) | No user-controlled path components. |
| Browser token storage | In memory only | Limits theft via XSS persistence; CSP restricts scripts to same origin. |

## Canonical signing payload

```
AUTOLINK-FW-MANIFEST-V1\n
firmware_id=<len>:<value>\n
version=<len>:<value>\n
hardware_id=<len>:<value>\n
sha256=<len>:<value>\n
size=<len>:<decimal>\n
security_counter=<len>:<decimal>\n
min_current_version=<len>:<value>\n
key_id=<len>:<value>\n
release_notes=<len>:<value>\n
simulate_unhealthy=<len>:true|false\n
```

`<len>` is the UTF-8 byte length of the value. Length prefixes make the encoding unambiguous even if a value
contains `=` or a newline. `simulate_unhealthy` is a simulation hook; it is signed so that it cannot be toggled
in transit.

## Key handling

- `scripts/dev_setup.py` generates a fresh development key per checkout into `.dev/` (git-ignored, mode 0600).
- Unit-test fixtures use keys derived from fixed public strings (`scripts/gen_ecu_fixtures.py`); they are test-only
  and never placed in a runtime trust store.
- Production: keep the private key in an HSM or cloud KMS, sign in a controlled release pipeline, record each
  signature, and plan trust-store rotation as a signed update (not implemented).
