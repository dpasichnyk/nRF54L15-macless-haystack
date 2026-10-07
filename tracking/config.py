from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path

from tracking.crypto import load_tags

_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE properties SYSTEM "http://java.sun.com/dtd/properties.dtd">
<properties>
  <entry key="protocols.enable">osmand</entry>
  <entry key="osmand.port">5055</entry>
  <entry key="server.buffering.threshold">0</entry>
  <entry key="web.override">/opt/traccar/data/override</entry>
  <entry key="media.path">/opt/traccar/data/media</entry>
  <entry key="database.driver">org.postgresql.Driver</entry>
  <entry key="database.url">jdbc:postgresql://tracking-db:5432/traccar</entry>
  <entry key="database.user">traccar</entry>
  <entry key="database.password">{password}</entry>
  <entry key="logger.level">warning</entry>
  <entry key="logger.console">true</entry>
  <entry key="filter.duplicate">false</entry>
  <entry key="filter.past">0</entry>
</properties>
"""


def initialize(state: Path, keys: Path) -> None:
    _ = load_tags(keys.read_bytes())
    if state.exists():
        for name in ("admin.json", "collector.json", "db-password", "traccar.xml", "compose.env"):
            if not (state / name).is_file():
                raise ValueError("Tracking state is incomplete; restore its credentials from backup")
        return
    state.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".tracking-init-", dir=state.parent))
    try:
        password = secrets.token_urlsafe(32)
        contents = {
            "db-password": password,
            "traccar.xml": _XML.format(password=password),
            "compose.env": f"TRACKING_UID={os.getuid()}\nTRACKING_GID={os.getgid()}\n",
            "admin.json": json.dumps({"email": "owner@example.invalid", "password": secrets.token_urlsafe(32)}),
            "collector.json": json.dumps({"email": "collector@example.invalid", "password": secrets.token_urlsafe(32)}),
        }
        for name, body in contents.items():
            path = temporary / name
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                _ = stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        for directory in ("traccar-data", "backups"):
            (temporary / directory).mkdir(mode=0o700)
        _ = temporary.rename(state)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
