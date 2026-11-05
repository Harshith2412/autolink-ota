# Technical interview preparation

Twenty questions an interviewer is likely to ask about this project, with answers grounded in the code.

**1. Walk me through an update end to end.**
An engineer uploads a manifest and image; the backend verifies the Ed25519 signature and SHA-256 and stores the
blob by digest. The engineer drafts a campaign; compatibility is checked. A different admin approves; each target
gets a deployment with a per-vehicle command sequence number and expiry. On its next heartbeat the ECU receives
the command, fetches the manifest and image, verifies signature, hardware, version, security counter and digest,
writes the inactive slot, switches the boot slot, runs a health check and commits. Every transition is an event in
a persistent outbox the backend ingests idempotently.

**2. Why does the ECU re-verify when the backend already did?**
Because the backend is not the root of trust. If the backend, blob store or network is compromised, the ECU still
refuses anything not signed by a key in its own trust store. The `ecu_revoked_signing_key` scenario shows this:
the backend trusts the key, the ECU has revoked it, and the ECU rejects the package.

**3. What exactly is signed, and why not just sign the JSON?**
A canonical, length-prefixed list of manifest fields. JSON has no canonical serialization; whitespace or key
order would differ between Python and C++. A fixed format lets both verifiers rebuild identical bytes, which a
test checks across the tool, the backend and a C++ fixture.

**4. How do you guarantee the state file is never half-written?**
Write to a temp file, `fsync`, `rename` over the original, `fsync` the directory. Rename is atomic on POSIX
filesystems, so after a crash you see the old or new file, never a mix. Changes that belong together, such as the
boot-slot switch and entering ACTIVATING, go into one write.

**5. What happens if power fails during each state?**
Downloading resumes with an HTTP Range request from the partial file. Verifying and staging rerun because
they are idempotent. READY_TO_ACTIVATE continues. ACTIVATING or HEALTH_CHECK is treated as an unconfirmed boot and
rolled back. After COMMITTED the new version stays. Each case has a forked unit test and an experiment scenario.

**6. Why roll back an unconfirmed boot instead of retrying?**
It is the conservative choice that mirrors A/B bootloaders with a confirmation flag: if the new image never
confirmed itself healthy, assume it might be the cause. A bounded retry is reasonable too; it trades availability
of the new version against the risk of a boot loop.

**7. How does anti-rollback work, and what's its weakness here?**
Two checks: the target version must be newer than the installed one, and the security counter must be at least a
persisted floor. The floor rises only when an update commits, so a failed update can't lock the ECU out. The
weakness is that the floor lives in a writable file; real hardware would use OTP fuses or an RPMB partition.

**8. How do you prevent a command from running twice?**
Commands carry a per-vehicle monotonic sequence. The ECU executes only `seq > last_command_seq` and advances the
counter even when it rejects a command. The backend resends pending commands until the ECU reports a higher
sequence, so delivery is at-least-once and execution is at-most-once.

**9. And duplicate events on the backend?**
A unique constraint on `(vehicle_id, event_seq)` with `ON CONFLICT DO NOTHING`, plus a rule that terminal
deployment statuses never change. I mutation-tested that rule: removing it fails a test.

**10. Tell me about a bug the fault injection found.**
Under connection resets, the dashboard showed a vehicle on 1.0.0 after it had committed 1.1.0. The installed version
came only from heartbeats, which are best-effort, and the last one was dropped. I made the backend derive the
version from STATE events, which travel through the retried outbox, with a watermark so out-of-order events can't
regress it. That took a new migration.

**11. How do you know your tests can fail?**
I introduced defects on purpose and reran: disabling signature verification failed three C++ tests; letting late
events overwrite terminal status failed a backend test; serving firmware to non-targeted vehicles failed another.

**12. How is the fault injection realistic, and where is it not?**
It runs the real backend and the compiled ECU over real sockets. A TCP proxy injects resets, latency, truncation
and outages. Since TCP retransmits packet loss, I model loss per connection, which is how applications experience
it. Power loss is the process exiting right after a durable write; kills are random SIGKILLs. Not realistic: flash
behaviour, bootloaders, cellular latency.

**13. Your kill test initially passed every time. Why was that a problem?**
The ECU finished a loopback update in under 20 ms, so the timed SIGKILL almost always landed after completion; the
test proved nothing. I added link latency to widen the window, and the recorded runs show downloads interrupted
and resumed. Even then, no kill landed during activation, and the report says so explicitly.

**14. How is authorization enforced?**
HS256 JWTs with pinned algorithm, audience, issuer and expiry; the role is re-read from the database on each
request, so a demotion takes effect immediately. Tests cover tampered tokens, `alg=none`, wrong keys and expiry.
Campaign approval needs an admin who did not create it.

**15. How do vehicles authenticate, and what would you change for production?**
A 256-bit random token per vehicle, stored as a SHA-256 hash, sent with the vehicle id. A vehicle can only post as
itself and only fetch firmware targeted at it. For production: mutual TLS with a per-device key in a secure
element, so the credential can't simply be copied off the ECU.

**16. What's the biggest security gap?**
Signing-key compromise. Revocation lists exist in both trust stores, but distributing a new trust store isn't
implemented, and it would itself have to be a signed update. Second is the lack of TLS in the local stack.

**17. Why Flask and SQLite rather than FastAPI and PostgreSQL?**
The build environment had no network, so I couldn't install them. I chose to ship something I could run and test.
The layering (routes, services, repositories) is the same; porting means replacing route decorators with FastAPI
routers and the validator with Pydantic models, and swapping the SQL driver.

**18. How would you add MQTT?**
Implement the `CloudLink` interface over an MQTT client: heartbeat and telemetry at QoS 0, status and DTCs at QoS 1,
a retained command topic per vehicle, and Last Will for connectivity. Topic ACLs limit each vehicle to its own
subtree. Deduplication stays in the application layer, because QoS 1 is at-least-once and QoS 2 is per hop, not
end to end.

**19. How would this scale to a real fleet?**
PostgreSQL and multiple stateless backend instances behind a load balancer; images from S3 or a CDN with signed
URLs instead of streaming through the API; an MQTT broker for control traffic; telemetry into a time-series store
with retention; staged rollouts by percentage with automatic halt on failure rates.

**20. What does this have to do with ISO 26262 or UNECE R156?**
R156 asks for a managed update process: identified versions, compatibility checks, recovery from failure and
records of what was released to which vehicle, which is what campaigns, deployments and the audit log do. 26262
shaped the fail-safe defaults. I used them as design references only; the project makes no compliance claims.
