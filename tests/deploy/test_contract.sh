#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file=$root/compose.yaml
dockerfile=$root/Dockerfile.macless-haystack
config_file=$root/deploy/endpoint/config.ini
requirements_lock=$root/deploy/requirements.lock
two_factor_patch=$root/deploy/patches/macless-haystack-2fa-idmsa.patch
rendered=$(mktemp)
trap 'rm -f "$rendered"' EXIT HUP INT TERM

docker compose -f "$compose_file" config --format json > "$rendered"

uv run python - "$rendered" "$root" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as rendered_file:
    config = json.load(rendered_file)

root = sys.argv[2]
services = config["services"]
assert set(services) == {"anisette", "endpoint"}

endpoint = services["endpoint"]
assert endpoint["ports"] == [{
    "mode": "ingress",
    "host_ip": "127.0.0.1",
    "target": 6176,
    "published": "6176",
    "protocol": "tcp",
}]
assert len(endpoint["volumes"]) == 1, endpoint["volumes"]
mount = endpoint["volumes"][0]
assert mount["type"] == "bind", mount
assert mount["source"] == os.path.join(root, "deploy/endpoint"), mount
assert mount["target"] == "/app/endpoint/data", mount
assert mount.get("read_only", False) is False, mount

anisette = services["anisette"]
assert "ports" not in anisette
assert len(anisette["volumes"]) == 1, anisette["volumes"]
mount = anisette["volumes"][0]
assert mount["type"] == "volume", mount
assert mount["source"] == "anisette-state", mount
assert mount["target"] == "/home/Alcoholic/.config/anisette-v3", mount
assert mount.get("read_only", False) is False, mount
assert config["volumes"]["anisette-state"]["name"].endswith("anisette-state")
PY

grep -Fq 'dadoum/anisette-v3-server@sha256:1e20384985d3c49965f444bef39d627768dacc39ea0dca91f2a535edb7591ba3' "$compose_file"

grep -Fq 'python:3.12-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217' "$dockerfile"
grep -Fq '0bda271b8bd0cc37194dfba1845cd48954cba4cc' "$dockerfile"
grep -Fq 'COPY --from=builder /source/endpoint /app/endpoint' "$dockerfile"
grep -Fq 'git -C /source apply /tmp/macless-haystack-2fa-idmsa.patch' "$dockerfile"
grep -Fq 'rm -f /source/endpoint/updateRepo /source/endpoint/data/rename_me.pem' "$dockerfile"
! grep -Fq 'git pull' "$dockerfile"
grep -Fq -- '--require-hashes -r /tmp/requirements.lock' "$dockerfile"
grep -Fq -- '--hash=sha256:' "$requirements_lock"
grep -Fq '+            "https://idmsa.apple.com/appleauth/auth/verify/phone/securitycode",' "$two_factor_patch"
grep -Fq -- '-            "https://gsa.apple.com/auth/verify/phone/securitycode",' "$two_factor_patch"
grep -Fq -- '-            verify=False,' "$two_factor_patch"
grep -Fq 'https://github.com/dchristl/macless-haystack/pull/226' "$two_factor_patch"

docker compose -f "$compose_file" build endpoint
docker compose -f "$compose_file" run --rm --no-deps --entrypoint sh endpoint -c '
    ! grep -Fq "verify=False" endpoint/register/pypush_gsa_icloud.py
    grep -Fq "https://idmsa.apple.com/appleauth/auth/verify/phone/securitycode" endpoint/register/pypush_gsa_icloud.py
'

grep -Fqx 'port=6176' "$config_file"
grep -Fqx 'binding_address=0.0.0.0' "$config_file"
grep -Fqx 'anisette_url=http://anisette:6969' "$config_file"
grep -Fqx 'loglevel=INFO' "$config_file"
grep -Fqx 'appleid=' "$config_file"
grep -Fqx 'appleid_pass=' "$config_file"
grep -Fqx 'endpoint_user=' "$config_file"
grep -Fqx 'endpoint_pass=' "$config_file"
grep -Fqx '/deploy/endpoint/auth.json' "$root/.gitignore"
grep -Fqx '*' "$root/.dockerignore"
grep -Fqx '!deploy/requirements.lock' "$root/.dockerignore"
grep -Fqx '!deploy/patches/macless-haystack-2fa-idmsa.patch' "$root/.dockerignore"
grep -Fqx '.DEFAULT_GOAL := help' "$root/Makefile"
grep -Fq 'provision_p224_keys.py --count 50' "$root/Makefile"
grep -Fq 'run --rm --no-deps endpoint rm -f /app/endpoint/data/auth.json' "$root/Makefile"
grep -Fq 'Refusing setup: deploy/endpoint/auth.json already exists. Run make up to use it or make reset-auth then make setup to replace it.' "$root/Makefile"
