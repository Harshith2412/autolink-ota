# Local installation

Verified on Ubuntu 24.04 with g++ 13, Python 3.12, Node 22. macOS should work with Homebrew OpenSSL 3
(`PKG_CONFIG_PATH=$(brew --prefix openssl@3)/lib/pkgconfig`), but was not tested.

## Prerequisites

- g++ ≥ 11 or clang ≥ 14, make, OpenSSL 3 (`libssl-dev`), pkg-config
- Python 3.12 with `pip install -r backend/requirements.txt`
- Node ≥ 20 and npm (dashboard), `npx playwright install chromium` for browser tests
- Optional: CMake ≥ 3.20 for the GoogleTest build

## Steps

```bash
make ecu                        # builds ecu/build-make/autolink-ecu and the unit tests
cd frontend && npm install && npm run build && cd ..   # or: node scripts/build-offline.mjs
make setup                      # .dev/: dev signing key, trust store, JWT secret, accounts (printed once)
make serve                      # backend + dashboard on http://127.0.0.1:8000
```

Sign in at http://127.0.0.1:8000 with an account from `.dev/credentials.txt`. For dashboard development with hot
reload, run `npm run dev` in `frontend/` (port 5173, proxies `/api` to 8000).

## Run a vehicle

```bash
python3 scripts/demo.py register VIN-DEMO-001
AUTOLINK_DEVICE_TOKEN=$(cat .dev/ecu-VIN-DEMO-001.token) \
  ecu/build-make/autolink-ecu --config .dev/ecu-VIN-DEMO-001.json
```

The ECU heartbeats every second until stopped (Ctrl-C). Its state lives in `.dev/ecu-state-VIN-DEMO-001/`;
delete that directory to "factory reset" the simulated ECU.

## Tests

```bash
make test            # all suites
make experiments     # fault matrix, about 4 minutes on 1 CPU
python3 scripts/collect_evidence.py   # regenerate docs/verification and evidence/
```

## CMake build (not run in the original build environment)

```bash
cmake -S ecu -B ecu/build && cmake --build ecu/build -j && ctest --test-dir ecu/build --output-on-failure
```
