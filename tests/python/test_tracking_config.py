import base64
import json
import stat
from pathlib import Path

import pytest

from tracking.config import initialize


def test_initialize_preserves_credentials_and_uses_private_permissions(tmp_path: Path) -> None:
    keys = tmp_path / "keys.json"
    _ = keys.write_text(json.dumps([{
        "id": 1, "name": "tag", "privateKey": base64.b64encode((1).to_bytes(28, "big")).decode(),
    }]))
    state = tmp_path / "state"
    initialize(state, keys)
    before = (state / "admin.json").read_bytes()
    initialize(state, keys)
    assert (state / "admin.json").read_bytes() == before
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    for name in ("admin.json", "collector.json", "db-password", "traccar.xml", "compose.env"):
        assert stat.S_IMODE((state / name).stat().st_mode) == 0o600
    assert (state / "db-password").read_text() in (state / "traccar.xml").read_text()


def test_incomplete_state_is_not_silently_replaced(tmp_path: Path) -> None:
    keys = tmp_path / "keys.json"
    _ = keys.write_text("[]")
    state = tmp_path / "state"
    state.mkdir()
    _ = (state / "admin.json").write_text("preserve")
    with pytest.raises(ValueError, match="incomplete"):
        initialize(state, keys)
    assert (state / "admin.json").read_text() == "preserve"
