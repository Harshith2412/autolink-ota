# Standards awareness notes

These notes describe which ideas from automotive standards shaped the prototype. They are not conformance claims.

| Standard | Idea applied here | Where | Not done |
|---|---|---|---|
| UNECE R156 (software update management) | Updates identified by version, recorded per vehicle; compatibility checked before rollout; failure recovery; audit of who released what | campaigns, deployments, audit log, A/B recovery | SUMS organisation processes, RXSWIN tracking, user notification and vehicle-state preconditions |
| UNECE R155 / ISO/SAE 21434 (cybersecurity) | Threat analysis with assets, threats, mitigations and residual risk; authenticity and integrity of updates | `docs/security/threat-model.md` | Formal TARA with attack feasibility and impact ratings, CSMS |
| ISO 26262 (functional safety) | Fail-safe default: never activate an unverified image, revert unconfirmed boots | state machine | No ASIL classification, no safety case; OTA ECUs here are treated as QM |
| Automotive SPICE | Requirements with IDs, bidirectional traceability, test levels, verification records | `docs/requirements/`, `docs/verification/` | Process assessment, work-product reviews |
| AUTOSAR | Separation of transport from application logic, similar in spirit to communication stacks; DTC concept from diagnostics | `CloudLink`, DTC handling | No AUTOSAR stack, RTE, UDS or DoIP |
