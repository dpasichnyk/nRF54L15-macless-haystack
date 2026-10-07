import base64
import json
import stat
from pathlib import Path

import pytest

from deploy.report_fetch import JSON_LOADS, JsonValue
from tracking.crypto import load_tags
from tracking.devices import MergeError, main, merge, read_devices, summarize, write


def encoded_key(seed: int) -> str:
    return base64.b64encode(bytes([seed]) * 28).decode()


def device(
    identifier: int, name: str, seed: int, **extra: JsonValue
) -> dict[str, JsonValue]:
    return {
        "name": name,
        "id": identifier,
        "colorComponents": [0, 1, 0, 1],
        "privateKey": encoded_key(seed),
        "additionalKeys": [encoded_key(seed + 100)],
        "isActive": True,
        **extra,
    }


def source(tmp_path: Path, name: str, devices: list[dict[str, JsonValue]]) -> Path:
    path = tmp_path / name
    _ = path.write_text(json.dumps(devices))
    return path


def _device_count(path: Path) -> int:
    content = JSON_LOADS(path.read_bytes())
    assert isinstance(content, list)
    return len(content)


def test_merge_orders_devices_by_id_and_keeps_unknown_fields(tmp_path: Path) -> None:
    second = source(tmp_path, "b.json", [device(2, "second", 2, icon="x")])
    first = source(tmp_path, "a.json", [device(1, "first", 1)])

    merged = merge([second, first])

    assert [item["id"] for item in merged] == [1, 2]
    assert merged[1]["icon"] == "x"
    assert merged[0]["colorComponents"] == [0, 1, 0, 1]


def test_duplicate_device_across_sources_is_deduplicated(tmp_path: Path) -> None:
    original = source(tmp_path, "one.json", [device(1, "tag", 1)])
    copied = source(tmp_path, "copy.json", [device(1, "tag", 1)])

    assert merge([original, copied]) == merge([original])


def test_conflicting_device_with_same_id_is_rejected(tmp_path: Path) -> None:
    first = source(tmp_path, "one.json", [device(1, "tag", 1)])
    second = source(tmp_path, "two.json", [device(1, "tag", 9)])

    with pytest.raises(MergeError, match="differs between sources"):
        _ = merge([first, second])


@pytest.mark.parametrize("payload", ['{"id": 1}', "[1]", '["text"]'])
def test_malformed_sources_are_rejected(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "bad.json"
    _ = path.write_text(payload)

    with pytest.raises(MergeError):
        _ = read_devices(path)


def test_device_without_integer_id_is_rejected(tmp_path: Path) -> None:
    path = source(tmp_path, "bad.json", [{"name": "tag"}])

    with pytest.raises(MergeError, match="integer id"):
        _ = merge([path])


def test_shared_keys_between_active_tags_are_rejected(tmp_path: Path) -> None:
    first = source(tmp_path, "one.json", [device(1, "a", 1)])
    second = source(tmp_path, "two.json", [device(2, "b", 1)])

    with pytest.raises(MergeError, match="must not share keys"):
        _ = merge([first, second])


def test_inactive_tag_may_reuse_keys(tmp_path: Path) -> None:
    first = source(tmp_path, "one.json", [device(1, "a", 1)])
    second = source(tmp_path, "two.json", [device(2, "b", 1, isActive=False)])

    assert len(merge([first, second])) == 2


def test_write_is_atomic_private_and_replaces_previous_content(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "import.json"
    write(output, [device(1, "tag", 1)])

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert _device_count(output) == 1

    write(output, [device(1, "tag", 1), device(2, "other", 2)])

    assert _device_count(output) == 2
    assert not list(output.parent.glob(".*import.json.*"))


def test_written_import_is_loadable_by_the_collector(tmp_path: Path) -> None:
    output = tmp_path / "import.json"
    write(output, [device(1, "a", 1), device(2, "b", 2)])

    tags = load_tags(output.read_bytes())

    assert [tag.unique_id for tag in tags] == ["nrf5-tag-1", "nrf5-tag-2"]


def test_main_reports_missing_sources_and_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    present = source(tmp_path, "one.json", [device(1, "tag", 1)])
    output = tmp_path / "import.json"

    assert main([str(output), str(tmp_path / "absent.json")]) == 1
    assert "missing source files" in capsys.readouterr().err

    assert main([str(output), str(present)]) == 0
    captured = capsys.readouterr().out
    assert "merged 1 device(s)" in captured
    assert "id=1" in captured


def test_summarize_counts_additional_keys() -> None:
    text = summarize([device(1, "tag", 1), {"id": 2, "name": "plain"}])

    assert text.splitlines() == ["  id=1 name=tag keys=2", "  id=2 name=plain keys=1"]