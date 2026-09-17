#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
temporary=$(mktemp -d)
server_pid=

cleanup() {
    if [ -n "$server_pid" ]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    rm -rf "$temporary"
}

trap cleanup EXIT HUP INT TERM

cat > "$temporary/anisette_server.py" <<'PY'
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sys

count_path = Path(sys.argv[1])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/unready":
            self.send_response(503)
            self.end_headers()
            return

        count = int(count_path.read_text()) if count_path.exists() else 0
        count += 1
        count_path.write_text(str(count))

        if count == 1:
            self.send_response(503)
            self.end_headers()
            return

        if count == 2:
            body = (
                b'{"X-Apple-I-MD":"ready",'
                b'"X-Apple-I-MD-M":"ready"'
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = json.dumps({
            "X-Apple-I-MD": "ready",
            "X-Apple-I-MD-M": "ready",
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(server.server_address[1], flush=True)
server.serve_forever()
PY

python3 "$temporary/anisette_server.py" "$temporary/request_count" \
    > "$temporary/port" 2> "$temporary/server.err" &
server_pid=$!

attempt=0
while [ ! -s "$temporary/port" ] && [ "$attempt" -lt 5 ]; do
    sleep 1
    attempt=$((attempt + 1))
done

if [ ! -s "$temporary/port" ]; then
    printf '%s\n' 'Toy anisette server did not start.' >&2
    exit 1
fi

cat > "$temporary/compose" <<'SH'
#!/bin/sh
set -eu

case "$1" in
    version | build | up)
        exit 0
        ;;
    run)
        shift
        while [ "$#" -gt 0 ]; do
            case "$1" in
                --rm | --no-deps | -T)
                    shift
                    ;;
                -e)
                    export "$2"
                    shift 2
                    ;;
                endpoint)
                    shift
                    break
                    ;;
                *)
                    printf 'Unexpected compose run argument: %s\n' "$1" >&2
                    exit 1
                    ;;
            esac
        done

        case "$1" in
            python)
                case "$2" in
                    -)
                        exec "$PYTHON" -
                        ;;
                    -c)
                        case "$3" in
                            *endpoint.register.apple_cryptography*)
                                : > "$FAKE_AUTH"
                                ;;
                            *)
                                printf '%s\n' 'Expected readiness probe to use python -.' >&2
                                exit 1
                                ;;
                        esac
                        ;;
                    *)
                        printf 'Unexpected python argument: %s\n' "$2" >&2
                        exit 1
                        ;;
                esac
                ;;
            chmod)
                exit 0
                ;;
            *)
                printf 'Unexpected endpoint command: %s\n' "$1" >&2
                exit 1
                ;;
        esac
        ;;
    *)
        printf 'Unexpected compose command: %s\n' "$1" >&2
        exit 1
        ;;
esac
SH
chmod +x "$temporary/compose"

mkdir "$temporary/endpoint"
auth="$temporary/auth.json"
url="http://127.0.0.1:$(cat "$temporary/port")/"

FAKE_AUTH="$auth" PYTHON=python3 \
    make -C "$root" setup \
    COMPOSE="$temporary/compose" \
    AUTH="$auth" \
    ENDPOINT_DATA="$temporary/endpoint" \
    ANISETTE_READY_URL="$url"

[ -f "$auth" ]
requests=0
if [ -f "$temporary/request_count" ]; then
    requests=$(cat "$temporary/request_count")
fi
if [ "$requests" -ne 3 ]; then
    printf 'Expected three bounded anisette probes, got %s.\n' "$requests" >&2
    exit 1
fi

unready_auth="$temporary/unready-auth.json"
if FAKE_AUTH="$unready_auth" PYTHON=python3 \
    make -C "$root" setup \
    COMPOSE="$temporary/compose" \
    AUTH="$unready_auth" \
    ENDPOINT_DATA="$temporary/endpoint" \
    ANISETTE_READY_URL="${url}unready" \
    > "$temporary/unready.out" 2> "$temporary/unready.err"; then
    printf '%s\n' 'Expected setup to fail when Anisette stays unavailable.' >&2
    exit 1
fi

grep -Fq "Timed out waiting for Anisette at ${url}unready after 12 attempts:" \
    "$temporary/unready.err"

if [ -e "$unready_auth" ]; then
    printf '%s\n' 'Readiness exhaustion unexpectedly created an auth artifact.' >&2
    exit 1
fi
