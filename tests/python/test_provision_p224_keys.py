from __future__ import annotations

import base64
import csv
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import TypedDict, TypeGuard, cast

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from scripts import provision_p224_keys as provisioner

REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "provision_p224_keys.py"
EXAMPLE_PUBLIC_X = "b70e0cbd6bb4bf7f321390b94a03c1d356c21122343280d6115c1d21"


class DeviceRecord(TypedDict):
    name: str
    id: int
    colorComponents: list[int]
    privateKey: str
    icon: str
    isActive: bool
    additionalKeys: list[str]


def is_int_list(value: object) -> TypeGuard[list[int]]:
    if not isinstance(value, list):
        return False
    return all(isinstance(item, int) for item in cast(list[object], value))


def is_string_list(value: object) -> TypeGuard[list[str]]:
    if not isinstance(value, list):
        return False
    return all(isinstance(item, str) for item in cast(list[object], value))


def is_device_record(value: object) -> TypeGuard[DeviceRecord]:
    if not isinstance(value, dict):
        return False
    record = cast(dict[str, object], value)
    return (
        list(record)
        == [
            "name",
            "id",
            "colorComponents",
            "privateKey",
            "icon",
            "isActive",
            "additionalKeys",
        ]
        and isinstance(record.get("name"), str)
        and isinstance(record.get("id"), int)
        and is_int_list(record.get("colorComponents"))
        and isinstance(record.get("privateKey"), str)
        and isinstance(record.get("icon"), str)
        and isinstance(record.get("isActive"), bool)
        and is_string_list(record.get("additionalKeys"))
    )


def parse_devices_json(content: str) -> DeviceRecord:
    decoded = cast(object, json.loads(content))
    assert isinstance(decoded, list)
    records = cast(list[object], decoded)
    assert len(records) == 1
    assert is_device_record(records[0])
    return records[0]


def run_provisioner_at_paths(
    devices_path: Path, public_keys_path: Path, count: int, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--count",
            str(count),
            "--devices-output",
            str(devices_path),
            "--public-keys-output",
            str(public_keys_path),
        ],
        capture_output=True,
        check=check,
        text=True,
    )


def run_provisioner(
    temporary_path: Path, count: int, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    devices_path = temporary_path / "devices.json"
    public_keys_path = temporary_path / "public-x.csv"
    return run_provisioner_at_paths(devices_path, public_keys_path, count, check=check)


def load_outputs(temporary_path: Path) -> tuple[DeviceRecord, list[str]]:
    devices_path = temporary_path / "devices.json"
    public_keys_path = temporary_path / "public-x.csv"
    device = parse_devices_json(devices_path.read_text(encoding="ascii"))
    with public_keys_path.open(encoding="ascii", newline="") as stream:
        public_x_values = [row[0] for row in csv.reader(stream)]
    return (
        device,
        public_x_values,
    )


def test_valid_key_generation_and_derivation_match_when_generating_two_keys(
    tmp_path: Path,
) -> None:
    # Given
    completed = run_provisioner(tmp_path, 2)

    # When
    device, public_x_values = load_outputs(tmp_path)
    private_keys = [*device["additionalKeys"], device["privateKey"]]
    derived_public_x_values = [
        ec.derive_private_key(
            int.from_bytes(base64.b64decode(private_key), "big"), ec.SECP224R1()
        )
        .public_key()
        .public_numbers()
        .x.to_bytes(28, "big")
        .hex()
        for private_key in private_keys
    ]

    # Then
    assert completed.stdout.splitlines() == [
        f"devices_json={tmp_path / 'devices.json'}",
        f"public_x_csv={tmp_path / 'public-x.csv'}",
        "count=2",
    ]
    assert public_x_values == derived_public_x_values
    assert all(len(bytes.fromhex(value)) == 28 for value in public_x_values)


def test_devices_json_schema_when_generating_multiple_keys(tmp_path: Path) -> None:
    # Given
    _ = run_provisioner(tmp_path, 3)

    # When
    device, _ = load_outputs(tmp_path)

    # Then
    assert list(device) == [
        "name",
        "id",
        "colorComponents",
        "privateKey",
        "icon",
        "isActive",
        "additionalKeys",
    ]
    assert device["name"] == "nrf5-tag"
    assert device["id"] == 1
    assert device["colorComponents"] == [0, 1, 0, 1]
    assert device["icon"] == ""
    assert device["isActive"] is True
    assert isinstance(device["privateKey"], str)
    assert isinstance(device["additionalKeys"], list)
    assert len(device["additionalKeys"]) == 2
    assert all(
        len(base64.b64decode(private_key, validate=True)) == 28
        for private_key in [*device["additionalKeys"], device["privateKey"]]
    )


def test_distinct_device_id_and_name_when_provisioning_a_second_tag(
    tmp_path: Path,
) -> None:
    # Given
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--count",
            "2",
            "--devices-output",
            str(tmp_path / "devices.json"),
            "--public-keys-output",
            str(tmp_path / "public-x.csv"),
            "--device-id",
            "7",
            "--name",
            "nrf5-tag-b",
        ],
        capture_output=True,
        check=True,
        text=True,
    )

    # When
    device = parse_devices_json(
        (tmp_path / "devices.json").read_text(encoding="ascii")
    )

    # Then
    assert completed.returncode == 0
    assert device["id"] == 7
    assert device["name"] == "nrf5-tag-b"


@pytest.mark.parametrize(
    "arguments", [("--device-id", "0"), ("--device-id", "2147483648"), ("--name", "")]
)
def test_out_of_range_identity_is_rejected_when_provisioning(
    tmp_path: Path, arguments: tuple[str, str]
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--count",
            "1",
            "--devices-output",
            str(tmp_path / "devices.json"),
            "--public-keys-output",
            str(tmp_path / "public-x.csv"),
            *arguments,
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode != 0
    assert not (tmp_path / "devices.json").exists()


def test_private_output_mode_is_0600_when_provisioning(tmp_path: Path) -> None:
    # Given
    _ = run_provisioner(tmp_path, 1)

    # When
    mode = stat.S_IMODE((tmp_path / "devices.json").stat().st_mode)

    # Then
    assert mode == 0o600


def test_public_output_mode_is_0644_when_provisioning(tmp_path: Path) -> None:
    # Given
    _ = run_provisioner(tmp_path, 1)

    # When
    mode = stat.S_IMODE((tmp_path / "public-x.csv").stat().st_mode)

    # Then
    assert mode == 0o644


def test_invalid_count_creates_no_outputs(tmp_path: Path) -> None:
    # Given / When
    completed = run_provisioner(tmp_path, 0, check=False)

    # Then
    assert completed.returncode != 0
    assert not (tmp_path / "devices.json").exists()
    assert not (tmp_path / "public-x.csv").exists()


def test_count_above_firmware_capacity_creates_no_outputs(tmp_path: Path) -> None:
    # Given / When
    completed = run_provisioner(tmp_path, 51, check=False)

    # Then
    assert completed.returncode != 0
    assert not (tmp_path / "devices.json").exists()
    assert not (tmp_path / "public-x.csv").exists()


def test_existing_outputs_are_not_overwritten(tmp_path: Path) -> None:
    devices_path = tmp_path / "devices.json"
    public_keys_path = tmp_path / "public-x.csv"
    _ = devices_path.write_text("existing private data", encoding="ascii")
    _ = public_keys_path.write_text("existing public data", encoding="ascii")

    completed = run_provisioner(tmp_path, 1, check=False)

    assert completed.returncode != 0
    assert devices_path.read_text(encoding="ascii") == "existing private data"
    assert public_keys_path.read_text(encoding="ascii") == "existing public data"


@pytest.mark.parametrize("output_name", ["devices.json", "public-x.csv"])
def test_rejects_each_symlink_output_without_changing_target(
    tmp_path: Path, output_name: str
) -> None:
    # Given
    output_path = tmp_path / output_name
    target_path = tmp_path / "output-target"
    _ = target_path.write_text("target output", encoding="ascii")
    _ = output_path.symlink_to(target_path)

    # When
    completed = run_provisioner(tmp_path, 1, check=False)

    # Then
    assert completed.returncode != 0
    assert target_path.read_text(encoding="ascii") == "target output"


def test_rejects_output_paths_that_resolve_to_same_location(tmp_path: Path) -> None:
    # Given
    output_path = tmp_path / "output"

    # When
    completed = run_provisioner_at_paths(output_path, output_path, 1, check=False)

    # Then
    assert completed.returncode != 0
    assert not output_path.exists()


def test_publish_pair_preserves_replacement_after_public_link_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    devices_path = tmp_path / "devices.json"
    public_keys_path = tmp_path / "public-x.csv"
    replacement_content = b"replacement owned by another actor"
    original_link = os.link

    def replace_devices_then_fail_public_link(source: Path, destination: Path) -> None:
        if destination == public_keys_path:
            raise OSError("injected public link failure")
        original_link(source, destination)
        if destination == devices_path:
            devices_path.unlink()
            _ = devices_path.write_bytes(replacement_content)

    monkeypatch.setattr(os, "link", replace_devices_then_fail_public_link)

    # When
    with pytest.raises(OSError, match="injected public link failure"):
        provisioner.publish_pair(devices_path, b"private", public_keys_path, b"public")

    # Then
    assert devices_path.read_bytes() == replacement_content
    assert not public_keys_path.exists()


def test_publish_errors_do_not_disclose_existing_private_material(
    tmp_path: Path,
) -> None:
    # Given
    devices_path = tmp_path / "devices.json"
    private_material = "private material must never reach stderr"
    _ = devices_path.write_text(private_material, encoding="ascii")

    # When
    completed = run_provisioner(tmp_path, 1, check=False)

    # Then
    assert completed.returncode != 0
    assert private_material not in completed.stderr


def test_accepts_firmware_capacity_of_fifty_keys(tmp_path: Path) -> None:
    completed = run_provisioner(tmp_path, 50)

    device, public_x_values = load_outputs(tmp_path)
    assert completed.returncode == 0
    assert len(public_x_values) == 50
    assert len(device["additionalKeys"]) == 49


def test_generated_public_x_differs_from_example_fixture_when_provisioning(
    tmp_path: Path,
) -> None:
    # Given
    _ = run_provisioner(tmp_path, 1)

    # When
    _, public_x_values = load_outputs(tmp_path)

    # Then
    assert public_x_values != [EXAMPLE_PUBLIC_X]
