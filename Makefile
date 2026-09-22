COMPOSE ?= docker compose
PYTHON ?= python3
NPM ?= npm
NODE ?= node
API_URL ?= http://localhost:8000
WEB_URL ?= http://localhost:3000

RUFF_VERSION ?= 0.16.8
MYPY_VERSION ?= 2.3.1
# Day 1 introduces linting to a codebase that never had it (see pyproject.toml
# for the full rationale). `ruff check` runs clean across api/app + api/tests +
# ingestion-worker now (verified), but `ruff format --check` only runs against
# the files Day 1 actually authored/rewrote — reformatting untouched legacy
# files' internal style is out of scope. `mypy --strict` is scoped the same
# way: legacy modules aren't retroactively annotated, only imported (silently)
# for type resolution.
LINT_FORMAT_API = app/routers/documents.py app/core/errors.py app/services/queue.py tests/test_unit_queue.py tests/test_integration.py tests/test_unit_http.py
TYPECHECK_API = app/routers/documents.py app/services/queue.py app/core/errors.py

.PHONY: up down test test-backend test-worker test-verifiers test-mcp smoke tools build ci lint typecheck
up:
	$(COMPOSE) up --build -d --wait
down:
	$(COMPOSE) --profile ollama down
build:
	$(COMPOSE) build
tools:
	$(NPM) ci --prefix tools/mcp --ignore-scripts
test-verifiers:
	$(PYTHON) -m unittest discover -s tests -p 'test_verify*.py' -v
test-backend:
	$(COMPOSE) run --rm --no-deps -e RUN_DB_TESTS=1 -e TEST_SCHEMA_PATH=/tmp/init.sql -v "$(CURDIR)/infra/db/init.sql:/tmp/init.sql:ro" api python -m unittest discover -s tests -v
test-worker:
	$(COMPOSE) run --rm --no-deps ingestion-worker python -m unittest discover -s tests -v
test-mcp:
	$(NPM) --prefix tools/mcp test
	$(NODE) tools/mcp/smoke.mjs
test: test-verifiers test-backend test-worker test-mcp
lint:
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR):/repo:ro" -w /repo/api api sh -c "\
		pip install --quiet --no-cache-dir --target=/tmp/devtools ruff==$(RUFF_VERSION) && \
		export PYTHONPATH=/tmp/devtools RUFF_CACHE_DIR=/tmp/ruff-cache && \
		/tmp/devtools/bin/ruff format --check --config /repo/pyproject.toml $(LINT_FORMAT_API) && \
		/tmp/devtools/bin/ruff check --config /repo/pyproject.toml app tests"
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR):/repo:ro" -w /repo/ingestion-worker ingestion-worker sh -c "\
		pip install --quiet --no-cache-dir --target=/tmp/devtools ruff==$(RUFF_VERSION) && \
		export PYTHONPATH=/tmp/devtools RUFF_CACHE_DIR=/tmp/ruff-cache && \
		/tmp/devtools/bin/ruff format --check --config /repo/pyproject.toml worker.py tests && \
		/tmp/devtools/bin/ruff check --config /repo/pyproject.toml worker.py tests"
typecheck:
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR):/repo:ro" -w /repo/api api sh -c "\
		pip install --quiet --no-cache-dir --target=/tmp/devtools mypy==$(MYPY_VERSION) && \
		export PYTHONPATH=/tmp/devtools MYPY_CACHE_DIR=/tmp/mypy-cache && \
		/tmp/devtools/bin/mypy --config-file /repo/pyproject.toml $(TYPECHECK_API)"
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR):/repo:ro" -w /repo/ingestion-worker ingestion-worker sh -c "\
		pip install --quiet --no-cache-dir --target=/tmp/devtools mypy==$(MYPY_VERSION) && \
		export PYTHONPATH=/tmp/devtools MYPY_CACHE_DIR=/tmp/mypy-cache MYPYPATH=/repo/api && \
		/tmp/devtools/bin/mypy --config-file /repo/pyproject.toml worker.py"
smoke:
	$(PYTHON) scripts/verify.py smoke --api-url "$(API_URL)" --web-url "$(WEB_URL)"
ci:
	$(MAKE) up
	$(MAKE) test
	$(MAKE) smoke
# CI callers must always run down (also on failure). Volumes are preserved here.
