.DEFAULT_GOAL := help

.PHONY: help keys build flash setup up down logs status reset-auth test test-firmware test-deploy

COMPOSE := docker compose
AUTH := deploy/endpoint/auth.json
ENDPOINT_DATA := deploy/endpoint
KEY_DIR ?= $(HOME)/.local/share/nrf5-tag
DEVICES_JSON := $(KEY_DIR)/nrf5-tag_devices.json
PUBLIC_KEYS := $(KEY_DIR)/public-x.csv
NCS_VERSION := v3.2.1
BUILD_DIR := $(CURDIR)/build-ncs-3.2.1
BOARD := xiao_nrf54l15/nrf54l15/cpuapp

help:
	@printf '%s\n' \
		'make keys        Generate the private import file and firmware public key' \
		'make flash       Build and verified-flash the firmware' \
		'make setup       Register Apple credentials interactively and start the endpoint' \
		'make up          Start the registered endpoint' \
		'make down        Stop services without deleting data' \
		'make logs        Follow service logs' \
		'make status      Show service status' \
		'make reset-auth  Remove only the saved Apple token' \
		'make test        Run firmware and deployment checks'

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
		--chdir /opt/nordic/ncs/$(NCS_VERSION) -- west build \
		--pristine=always --no-sysbuild -b $(BOARD) -d "$(BUILD_DIR)" "$(CURDIR)"

flash: build
	nrfutil sdk-manager toolchain launch --ncs-version $(NCS_VERSION) \
		--chdir /opt/nordic/ncs/$(NCS_VERSION) -- west flash \
		-r openocd --verify -d "$(BUILD_DIR)"

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
	cmake -S tests/host -B /tmp/nrf5-tag-host -DCMAKE_C_FLAGS="-Wall -Wextra -Werror"
	cmake --build /tmp/nrf5-tag-host --clean-first --parallel 2
	ctest --test-dir /tmp/nrf5-tag-host --output-on-failure
	uv run --with pytest==9.1.1 --with cryptography==50.0.1 --with typer==0.27.2 pytest tests/python -q
	uv run --with ruff==0.16.5 ruff check scripts tests/python

test-deploy:
	sh tests/deploy/test_contract.sh
