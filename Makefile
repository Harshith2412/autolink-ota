# AutoLink OTA top-level tasks. Every target here was run in the build environment
# unless marked (unverified).
PY ?= python3
NODE_PATH ?= /opt/npm-tools/node_modules
export NODE_PATH

.PHONY: setup ecu test test-ecu test-backend test-frontend test-integration test-e2e experiments frontend serve demo clean

setup:            ## dev keys, trust store, secrets, accounts in .dev/
	$(PY) scripts/dev_setup.py

ecu:              ## build the ECU simulator and its tests (Makefile path)
	$(MAKE) -C ecu

frontend:         ## production build of the dashboard into frontend/dist
	cd frontend && (test -d node_modules/vite && npm run build || node scripts/build-offline.mjs)

test: test-ecu test-backend test-frontend test-integration test-e2e

test-ecu: ecu
	$(MAKE) -C ecu test

test-backend:
	cd backend && AUTOLINK_LOG_LEVEL=ERROR $(PY) -m unittest discover -s tests -t . -v

test-frontend:
	cd frontend && npx tsx --test tests/unit/*.test.ts

test-integration: ecu
	$(PY) -m unittest tests.integration.test_end_to_end -v

test-e2e: ecu frontend
	$(PY) -m unittest tests.integration.test_dashboard_e2e -v

experiments: ecu  ## full fault-injection matrix -> experiments/results/
	$(PY) experiments/runner/run_matrix.py

serve:            ## backend + built dashboard on http://127.0.0.1:8000
	set -a && . ./.dev/backend.env && set +a && cd backend && $(PY) -m app.cli serve --port 8000

clean:
	$(MAKE) -C ecu clean
	rm -rf frontend/dist experiments/results/results.jsonl
