.DEFAULT_GOAL := help

.PHONY: help keys build build-dev flash flash-dev monitor setup up down logs status reset-auth test test-firmware test-deploy
.PHONY: tracking-up tracking-down tracking-status tracking-logs tracking-backup tracking-replay test-tracking

COMPOSE := docker compose
AUTH := deploy/endpoint/auth.json
ENDPOINT_DATA := deploy/endpoint
# The readiness probe defaults to the Compose Anisette v1 endpoint.
ANISETTE_READY_URL ?= http://anisette:6969
KEY_DIR ?= $(HOME)/.local/share/nrf5-tag
DEVICES_JSON := $(KEY_DIR)/nrf5-tag_devices.json
PUBLIC_KEYS := $(KEY_DIR)/public-x.csv
NCS_VERSION := v3.2.1
NCS_DIR ?= /opt/nordic/ncs/$(NCS_VERSION)
PROFILE ?= production
ifeq ($(PROFILE),production)
EXTRA_CONF :=
else ifeq ($(PROFILE),development)
EXTRA_CONF := debug.conf
else
$(error PROFILE must be production or development)
endif
BUILD_DIR ?= $(CURDIR)/build-$(PROFILE)
BOARD := xiao_nrf54l15/nrf54l15/cpuapp
TRACKING_STATE_DIR ?= $(CURDIR)/.tracking
TRACKING_PORT ?= 8082
TRACKING_COMPOSE = TRACKING_STATE_DIR="$(TRACKING_STATE_DIR)" TRACKING_KEYS_FILE="$(DEVICES_JSON)" TRACKING_PORT="$(TRACKING_PORT)" $(COMPOSE) --env-file "$(TRACKING_STATE_DIR)/compose.env" -f compose.yaml -f compose.tracking.yaml
TRACKING_SETUP := uv run --with cryptography==50.0.1 python -m tracking.setup

help:
	@printf '%s\n' \
		'make keys        Generate the private import file and firmware public key' \
		'make build       Build and check the low-power production profile' \
		'make build-dev   Build and check the development profile with RTT logs' \
		'make flash       Build and verified-flash production firmware' \
		'make flash-dev   Build and verified-flash development firmware' \
		'make monitor     Read development RTT logs over USB (resets the board)' \
		'make setup       Register Apple credentials interactively and start the endpoint' \
		'make up          Start the registered endpoint' \
		'make down        Stop services without deleting data' \
		'make logs        Follow service logs' \
		'make status      Show service status' \
		'make reset-auth  Remove only the saved Apple token' \
		'make test        Run firmware and deployment checks' \
		'make tracking-up Start persistent collection and local Traccar UI' \
		'make tracking-down Stop tracking services without deleting history' \
		'make tracking-status Show tracking containers and history counts' \
		'make tracking-logs Follow tracking service logs' \
		'make tracking-backup Save consistent SQLite and PostgreSQL backups' \
		'make tracking-replay Reconcile stored positions with Traccar again' \
		'make test-tracking Run isolated Traccar integration tests'

keys:
	@set -eu; \
	for path in "$(DEVICES_JSON)" "$(PUBLIC_KEYS)" src/keys.c; do \
		if [ -e "$$path" ]; then printf '%s\n' "Refusing to overwrite $$path" >&2; exit 1; fi; \
	done; \
	mkdir -p "$(KEY_DIR)"; \
	chmod 700 "$(KEY_DIR)"; \
	uv run scripts/provision_p224_keys.py --count 50 \
		--devices-output "$(DEVICES_JSON)" \
		--public-keys-output "$(PUBLIC_KEYS)"; \
	uv run scripts/keys_csv_to_c.py "$(PUBLIC_KEYS)" src/keys.c

build:
	@test -f src/keys.c || { printf '%s\n' 'src/keys.c is missing; run make keys.' >&2; exit 1; }
	nrfutil sdk-manager toolchain launch --ncs-version $(NCS_VERSION) \
		--chdir "$(NCS_DIR)" -- west build \
		--pristine=always --no-sysbuild -b $(BOARD) -d "$(BUILD_DIR)" "$(CURDIR)" \
		-- -DEXTRA_CONF_FILE="$(EXTRA_CONF)"
	cmake -DBUILD_DIR="$(BUILD_DIR)" -DPROFILE=$(PROFILE) -P tests/firmware/check_profile.cmake

build-dev:
	$(MAKE) build PROFILE=development

flash-dev:
	$(MAKE) flash PROFILE=development

monitor: override PROFILE := development
monitor:
	@test -f "$(BUILD_DIR)/zephyr/zephyr.elf" || { printf '%s\n' 'Run make flash-dev before monitoring.' >&2; exit 1; }
	@set -eu; \
	environment=$$(nrfutil sdk-manager toolchain env --ncs-version $(NCS_VERSION) --as-script sh); \
	eval "$$environment"; \
	cd "$(NCS_DIR)"; \
	exec west rtt -r openocd -d "$(BUILD_DIR)"

flash: build
	nrfutil sdk-manager toolchain launch --ncs-version $(NCS_VERSION) \
		--chdir "$(NCS_DIR)" -- west flash \
		-r openocd --verify -d "$(BUILD_DIR)" \
		--config "$(NCS_DIR)/zephyr/boards/seeed/xiao_nrf54l15/support/openocd.cfg" \
		--config "$(CURDIR)/scripts/openocd-rram.cfg"

setup:
	@set -eu; \
	if ! $(COMPOSE) version >/dev/null 2>&1; then \
		printf '%s\n' 'Docker Compose is required.' >&2; \
		exit 1; \
	fi; \
	if [ -e "$(AUTH)" ]; then \
		printf '%s\n' 'Refusing setup: deploy/endpoint/auth.json already exists. Run make up to use it or make reset-auth then make setup to replace it.' >&2; \
		exit 1; \
	fi; \
	chmod 700 "$(ENDPOINT_DATA)"; \
	$(COMPOSE) build endpoint; \
	$(COMPOSE) up -d anisette; \
	$(COMPOSE) run --rm --no-deps -T \
		-e ANISETTE_READY_URL="$(ANISETTE_READY_URL)" endpoint \
		python - < scripts/wait_for_anisette.py; \
	$(COMPOSE) run --rm endpoint python -c 'from endpoint.register.apple_cryptography import registerDevice; registerDevice()'; \
	if [ ! -f "$(AUTH)" ]; then \
		printf '%s\n' 'Registration did not create deploy/endpoint/auth.json.' >&2; \
		exit 1; \
	fi; \
	$(COMPOSE) run --rm --no-deps endpoint chmod 600 /app/endpoint/data/auth.json; \
	$(COMPOSE) up -d endpoint

up:
	@set -eu; \
	if [ ! -f "$(AUTH)" ]; then \
		printf '%s\n' 'deploy/endpoint/auth.json is required; run make setup.' >&2; \
		exit 1; \
	fi; \
	chmod 700 "$(ENDPOINT_DATA)"; \
	$(COMPOSE) run --rm --no-deps endpoint chmod 600 /app/endpoint/data/auth.json; \
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

status:
	$(COMPOSE) ps

reset-auth:
	-$(COMPOSE) stop endpoint
	-$(COMPOSE) rm -f endpoint
	$(COMPOSE) run --rm --no-deps endpoint rm -f /app/endpoint/data/auth.json

test: test-firmware test-deploy

test-firmware:
	@set -eu; \
	build=$$(mktemp -d "$${TMPDIR:-/tmp}/nrf5-tag-host.XXXXXX"); \
	trap 'rm -rf "$$build"' EXIT HUP INT TERM; \
	cmake -S tests/host -B "$$build" -DCMAKE_C_FLAGS="-Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer"; \
	cmake --build "$$build" --parallel 2; \
	ctest --test-dir "$$build" --output-on-failure
	uv run --with pytest==9.1.1 --with cryptography==50.0.1 --with typer==0.27.2 pytest tests/python -q
	uv run --with ruff==0.16.5 ruff check scripts deploy/report_fetch.py tracking tests/python tests/integration
	uv run --with basedpyright==1.39.10 --with cryptography==50.0.1 --with typer==0.27.2 --with pytest==9.1.1 basedpyright scripts deploy/report_fetch.py tracking tests/python tests/integration

test-deploy:
	sh tests/deploy/test_setup_readiness.sh
	sh tests/deploy/test_contract.sh

tracking-up:
	@test -f "$(AUTH)" || { printf '%s\n' 'Register Apple access with make setup first.' >&2; exit 1; }
	$(TRACKING_SETUP) init --state "$(TRACKING_STATE_DIR)" --keys "$(DEVICES_JSON)"
	$(TRACKING_COMPOSE) build collector
	$(TRACKING_COMPOSE) run --rm --no-deps --user 0:0 --cap-add CHOWN --cap-add FOWNER --entrypoint python collector -c 'import os; os.chown("/data", int(os.environ["TRACKING_UID"]), int(os.environ["TRACKING_GID"])); os.chmod("/data", 0o700)'
	$(COMPOSE) up -d endpoint anisette
	$(TRACKING_COMPOSE) up -d tracking-db traccar
	$(TRACKING_SETUP) bootstrap --state "$(TRACKING_STATE_DIR)" --keys "$(DEVICES_JSON)" --url "http://127.0.0.1:$(TRACKING_PORT)"
	$(TRACKING_COMPOSE) up -d --force-recreate collector

tracking-down:
	$(TRACKING_COMPOSE) stop collector traccar tracking-db

tracking-status:
	$(TRACKING_COMPOSE) ps
	$(TRACKING_COMPOSE) exec -T collector python -m tracking status

tracking-logs:
	$(TRACKING_COMPOSE) logs -f collector traccar

tracking-replay:
	$(TRACKING_COMPOSE) exec -T collector python -m tracking replay

tracking-backup:
	@set -eu; umask 077; stamp=$$(date -u +%Y%m%dT%H%M%SZ); \
	$(TRACKING_COMPOSE) exec -T collector python -m tracking backup "/data/backups/$$stamp.sqlite3"; \
	$(TRACKING_COMPOSE) cp "collector:/data/backups/$$stamp.sqlite3" "$(TRACKING_STATE_DIR)/backups/$$stamp.sqlite3.tmp"; \
	chmod 600 "$(TRACKING_STATE_DIR)/backups/$$stamp.sqlite3.tmp"; \
	mv "$(TRACKING_STATE_DIR)/backups/$$stamp.sqlite3.tmp" "$(TRACKING_STATE_DIR)/backups/$$stamp.sqlite3"; \
	$(TRACKING_COMPOSE) exec -T tracking-db pg_dump -U traccar -d traccar \
	  > "$(TRACKING_STATE_DIR)/backups/$$stamp.sql.tmp"; \
	mv "$(TRACKING_STATE_DIR)/backups/$$stamp.sql.tmp" "$(TRACKING_STATE_DIR)/backups/$$stamp.sql"; \
	printf '%s\n' "Backups saved under $(TRACKING_STATE_DIR)/backups"

test-tracking:
	uv run --with pytest==9.1.1 --with cryptography==50.0.1 pytest tests/integration -q
