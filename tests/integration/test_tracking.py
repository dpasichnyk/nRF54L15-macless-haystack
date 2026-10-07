import base64
import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event
from typing import ClassVar, override
from urllib.parse import urlencode

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from deploy.report_fetch import JSON_LOADS
from tracking.bootstrap import bootstrap
from tracking.config import initialize
from tracking.crypto import load_tags
from tracking.http import HttpClient
from tracking.service import Collector
from tracking.store import Store
from tracking.traccar import Traccar, load_credentials

ROOT = Path(__file__).resolve().parents[2]


class EndpointFixture(BaseHTTPRequestHandler):
    reports: ClassVar[list[dict[str, str]]] = []

    def do_POST(self) -> None:
        request = JSON_LOADS(self.rfile.read(int(self.headers["Content-Length"])))
        assert isinstance(request, dict)
        assert request["ids"] == [self.reports[0]["id"]]
        assert request["days"] == 7
        body = json.dumps({"statusCode": "200", "results": self.reports}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)

    @override
    def log_message(self, format: str, *args: str) -> None:
        return


def fixture_report(timestamp: int, seed: int) -> dict[str, str]:
    key = ec.derive_private_key(1, ec.SECP224R1())
    ephemeral_key = ec.derive_private_key(seed, ec.SECP224R1())
    ephemeral = ephemeral_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    secret = ephemeral_key.exchange(ec.ECDH(), key.public_key())
    symmetric = hashlib.sha256(secret + b"\0\0\0\1" + ephemeral).digest()
    plain = (-338000000).to_bytes(4, "big", signed=True) + (1512000000).to_bytes(4, "big", signed=True) + bytes([20, 0])
    payload = (timestamp - 978307200).to_bytes(4, "big") + b"\x02" + ephemeral
    payload += AESGCM(symmetric[:16]).encrypt(symmetric[16:], plain, None)
    public_x = key.public_key().public_numbers().x.to_bytes(28, "big")
    return {"id": base64.b64encode(hashlib.sha256(public_x).digest()).decode(),
            "payload": base64.b64encode(payload).decode()}


def test_tracking_persists_same_second_history_and_recovers_after_outage(tmp_path: Path) -> None:
    state, keys = tmp_path / "state", tmp_path / "keys.json"
    _ = keys.write_text(json.dumps([{
        "id": 42, "name": "Acceptance", "privateKey": base64.b64encode((1).to_bytes(28, "big")).decode(),
    }]))
    initialize(state, keys)
    project = f"nrf5-tag-test-{uuid.uuid4().hex[:10]}"
    network = f"{project}-network"
    overlay = tmp_path / "ports.yaml"
    _ = overlay.write_text(
        'services:\n  traccar:\n    ports:\n      - "127.0.0.1:0:5055"\n'
        + '    environment:\n      CONFIG_USE_ENVIRONMENT_VARIABLES: "true"\n      LOGGER_LEVEL: info\n'
        + f'networks:\n  default:\n    external: true\n    name: "{network}"\n'
    )
    environment = dict(os.environ, TRACKING_STATE_DIR=str(state), TRACKING_KEYS_FILE=str(keys), TRACKING_PORT="0")
    command = ["docker", "compose", "-p", project,
               "--env-file", str(state / "compose.env"), "-f", str(ROOT / "compose.yaml"),
               "-f", str(ROOT / "compose.tracking.yaml"), "-f", str(overlay)]

    def compose(*args: str) -> str:
        result = subprocess.run(command + list(args), env=environment, cwd=ROOT,
                                check=False, capture_output=True, text=True, timeout=240)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    endpoint = HTTPServer(("127.0.0.1", 0), EndpointFixture)
    thread = threading.Thread(target=endpoint.serve_forever)
    thread.start()
    network_created = False
    try:
        for _ in range(5):
            address = uuid.uuid4().bytes
            result = subprocess.run(
                ["docker", "network", "create", "--subnet", f"10.{address[0]}.{address[1]}.0/24", network],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if result.returncode == 0:
                network_created = True
                break
            assert "overlaps" in result.stderr, result.stderr
        assert network_created, "Could not allocate an isolated test subnet"
        rendered = JSON_LOADS(compose("config", "--format", "json").encode())
        assert isinstance(rendered, dict) and isinstance(rendered.get("services"), dict)
        services = rendered["services"]
        assert isinstance(services, dict) and isinstance(services.get("collector"), dict)
        collector_config = services["collector"]
        assert isinstance(collector_config, dict) and isinstance(collector_config.get("volumes"), list)
        mounts = collector_config["volumes"]
        assert isinstance(mounts, list)
        data_mount = next(item for item in mounts if isinstance(item, dict) and item.get("target") == "/data")
        assert isinstance(data_mount, dict) and data_mount["type"] == "volume"
        _ = compose("up", "-d", "tracking-db", "traccar")
        api_url = f"http://{compose('port', 'traccar', '8082')}"
        ingest_url = f"http://{compose('port', 'traccar', '5055')}"
        tags = load_tags(keys.read_bytes())
        bootstrap(HttpClient(api_url, timeout=5), state, tags)
        sink = Traccar(HttpClient(api_url), HttpClient(ingest_url), load_credentials(state / "collector.json"))
        now = int(time.time())
        EndpointFixture.reports = [fixture_report(now - 60, 2), fixture_report(now - 60, 3)]
        source = HttpClient(f"http://127.0.0.1:{endpoint.server_port}")
        database = state / "collector" / "reports.sqlite3"
        with Store(database) as store:
            collector = Collector(store, source, sink)
            assert collector.cycle(tags, Event()), sink.api.json("GET", "api/positions")
            assert store.status()["delivered"] == 2
            assert collector.cycle(tags, Event())
            assert store.status()["reports"] == 2
        _ = compose("stop", "traccar")
        EndpointFixture.reports.append(fixture_report(now - 120, 4))
        with Store(database) as store:
            assert not Collector(store, source, sink).cycle(tags, Event())
            assert store.status()["reports"] == 3
            assert store.status()["pending"] == 1
        _ = compose("start", "traccar")
        api_url = f"http://{compose('port', 'traccar', '8082')}"
        sink.api.base_url = api_url
        sink.ingest.base_url = f"http://{compose('port', 'traccar', '5055')}"
        bootstrap(HttpClient(api_url, timeout=5), state, tags)
        with Store(database) as store:
            assert Collector(store, source, sink).cycle(tags, Event())
            assert store.status()["delivered"] == 3
            assert store.status()["pending"] == 0
            store.backup(state / "backups" / "history.sqlite3")
        reader = HttpClient(api_url)
        credentials = load_credentials(state / "collector.json")
        _ = reader.form("api/session", {"email": credentials.email, "password": credentials.password})
        devices = reader.json("GET", "api/devices")
        assert isinstance(devices, list) and len(devices) == 1
        device = devices[0]
        assert isinstance(device, dict)
        assert device["uniqueId"] != tags[0].unique_id
        assert isinstance(device.get("attributes"), dict)
        attributes = device["attributes"]
        assert isinstance(attributes, dict) and attributes["findmytagid"] == tags[0].unique_id
        device_id = device["id"]
        assert isinstance(device_id, int)
        query = urlencode({"deviceId": device_id,
                           "from": datetime.fromtimestamp(now - 240, timezone.utc).isoformat(),
                           "to": datetime.fromtimestamp(now + 1, timezone.utc).isoformat()})
        positions = reader.json("GET", f"api/positions?{query}")
        assert isinstance(positions, list) and len(positions) == 3
        for position in positions:
            assert isinstance(position, dict)
            assert position["latitude"] == -33.8 and position["longitude"] == 151.2
            assert position["accuracy"] == 20
            fields = position.get("attributes")
            assert isinstance(fields, dict)
            report_id = fields.get("findmyreportid")
            assert isinstance(report_id, str) and report_id.startswith("sha256:")
        latest = reader.json("GET", "api/positions")
        assert isinstance(latest, list) and len(latest) == 1
        current = latest[0]
        assert isinstance(current, dict) and isinstance(current.get("fixTime"), str)
        fixed = current["fixTime"]
        assert isinstance(fixed, str)
        assert int(datetime.fromisoformat(fixed.replace("Z", "+00:00")).timestamp()) == now - 60
        with Store(state / "backups" / "history.sqlite3") as snapshot:
            assert snapshot.status()["reports"] == 3
    except Exception:
        database_rows = subprocess.run(command + ["exec", "-T", "tracking-db", "psql", "-U", "traccar", "-d", "traccar",
                                                  "-Atc", "SELECT count(*) FROM tc_positions"],
                                       env=environment, cwd=ROOT, capture_output=True, text=True,
                                       timeout=15, check=False)
        print("Stored Traccar rows:", database_rows.stdout)
        logs = subprocess.run(command + ["logs", "--no-color", "traccar", "tracking-db"],
                              env=environment, cwd=ROOT, capture_output=True, text=True,
                              timeout=15, check=False)
        print(logs.stdout)
        raise
    finally:
        endpoint.shutdown()
        endpoint.server_close()
        thread.join()
        _ = subprocess.run(command + ["down", "--volumes", "--remove-orphans"],
                           env=environment, cwd=ROOT, capture_output=True, timeout=120, check=False)
        if network_created:
            _ = subprocess.run(["docker", "network", "rm", network], capture_output=True,
                               timeout=30, check=True)
