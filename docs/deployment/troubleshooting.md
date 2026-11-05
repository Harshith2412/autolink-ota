# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ConfigError: AUTOLINK_JWT_SECRET must be set` | Backend started without `.dev/backend.env` | `make setup`, then `make serve` (which sources it). |
| Login fails for every account | `.dev/` was regenerated but the old database remains, or vice versa | Delete `.dev/` entirely and run `make setup`. |
| Upload returns `BAD_SIGNATURE` for a package you just signed | The running backend uses a different trust store (for example a backend from an older `.dev/` still on port 8000) | Stop old backends (`ss -ltnp \| grep 8000`), restart with the current env. |
| Upload returns `DIGEST_MISMATCH` | Image file differs from the one that was signed | Re-sign the exact bytes you upload. |
| Campaign creation 422 `incompatible_targets` | Hardware mismatch, vehicle already on that version or newer, below `min_current_version`, or an active deployment | Read `details.vehicles[].issues`. Vehicles report their version only after the first heartbeat. |
| Approve returns 403 | The approver created the campaign | Approve with a different admin (`approver` in the dev accounts). |
| ECU exits with code 2 | Config or credentials error | Check the message; set `AUTOLINK_DEVICE_TOKEN`. |
| ECU exits with 3 | RECOVERY_FAILED latched | Inspect `journal.log`; `autolink-ecu --config … --service-reset`. |
| ECU says "persistent state belongs to a different vehicle" | Reused state directory | Use a separate `state_dir` per vehicle. |
| ECU heartbeat fails: `connect failed` | Backend down or wrong `backend_url` | The ECU retries with backoff; check the URL. Only `http://` is supported. |
| Deployment stuck PENDING | ECU not running, or the command expired | Run the ECU; expired commands become EXPIRED on the next heartbeat. |
| `undefined reference to EVP_…` when building | OpenSSL 3 dev package missing | Install `libssl-dev` / `openssl@3`. |
| Dashboard blank page | `frontend/dist` missing or `AUTOLINK_FRONTEND_DIST` wrong | Build the frontend; check `.dev/backend.env`. |
| Browser test cannot find Chromium | Playwright browsers not installed | `npx playwright install chromium`. |
