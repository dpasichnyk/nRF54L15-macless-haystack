from __future__ import annotations

import csv
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

REPOSITORY_ROOT = Path(__file__).parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "keys_csv_to_c.py"
VALID_PUBLIC_X = "706a46dc76dcb76798e60e6d89474788d16dc18032d268fd1a704fa6"


def public_x(private_scalar: int) -> str:
    return (
        ec.derive_private_key(private_scalar, ec.SECP224R1())
        .public_key()
        .public_numbers()
        .x.to_bytes(28, "big")
        .hex()
    )


def run_converter(
    input_path: Path, output_path: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(input_path), str(output_path)],
        capture_output=True,
        check=False,
        text=True,
    )


def test_converts_valid_public_x_csv(tmp_path: Path) -> None:
    input_path = tmp_path / "keys.csv"
    output_path = tmp_path / "keys.c"
    _ = input_path.write_text(VALID_PUBLIC_X + "\n", encoding="ascii")

    completed = run_converter(input_path, output_path)

    assert completed.returncode == 0
    assert output_path.read_bytes() == (
        b'#include <stdint.h>\n#include "keys.h"\n\n'
        b"const uint8_t beacon_keys[][BEACON_KEY_BYTES] = {\n"
        b"    {0x70, 0x6a, 0x46, 0xdc, 0x76, 0xdc, 0xb7, 0x67, 0x98, 0xe6, "
        b"0x0e, 0x6d, 0x89, 0x47, 0x47, 0x88, 0xd1, 0x6d, 0xc1, 0x80, 0x32, "
        b"0xd2, 0x68, 0xfd, 0x1a, 0x70, 0x4f, 0xa6},\n"
        b"};\n\n"
        b"const size_t beacon_key_count = sizeof(beacon_keys) / sizeof(beacon_keys[0]);\n"
        b"#ifdef CONFIG_N_KEYS\n"
        b"_Static_assert(sizeof(beacon_keys) / sizeof(beacon_keys[0]) == CONFIG_N_KEYS,\n"
        b'               "generated beacon key count does not match CONFIG_N_KEYS");\n'
        b"#endif\n"
    )
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o644


@pytest.mark.parametrize(("configured_count", "succeeds"), [(1, True), (2, False)])
def test_generated_table_enforces_configured_key_count(
    tmp_path: Path, configured_count: int, succeeds: bool
) -> None:
    input_path = tmp_path / "keys.csv"
    output_path = tmp_path / "keys.c"
    object_path = tmp_path / "keys.o"
    _ = input_path.write_text(VALID_PUBLIC_X + "\n", encoding="ascii")
    _ = run_converter(input_path, output_path)

    completed = subprocess.run(
        [
            "cc",
            "-std=c11",
            f"-DCONFIG_N_KEYS={configured_count}",
            "-I",
            str(REPOSITORY_ROOT / "include"),
            "-c",
            str(output_path),
            "-o",
            str(object_path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert (completed.returncode == 0) is succeeds


def test_accepts_public_x_split_into_28_byte_columns(tmp_path: Path) -> None:
    input_path = tmp_path / "keys.csv"
    output_path = tmp_path / "keys.c"
    byte_columns = ",".join(
        VALID_PUBLIC_X[index : index + 2] for index in range(0, len(VALID_PUBLIC_X), 2)
    )
    _ = input_path.write_text(byte_columns + "\n", encoding="ascii")

    completed = run_converter(input_path, output_path)

    assert completed.returncode == 0
    assert output_path.read_bytes().count(b"0x") == 28


def test_rejects_empty_csv_without_output(tmp_path: Path) -> None:
    input_path = tmp_path / "keys.csv"
    output_path = tmp_path / "keys.c"
    _ = input_path.write_text("", encoding="ascii")

    completed = run_converter(input_path, output_path)

    assert completed.returncode != 0
    assert not output_path.exists()


def test_rejects_blank_csv_rows_without_output(tmp_path: Path) -> None:
    input_path = tmp_path / "keys.csv"
    output_path = tmp_path / "keys.c"
    _ = input_path.write_text("\n  \n, , \n", encoding="ascii")

    completed = run_converter(input_path, output_path)

    assert completed.returncode != 0
    assert "input contains no keys" in completed.stderr
    assert not output_path.exists()


def test_rejects_invalid_p224_public_x_without_output(tmp_path: Path) -> None:
    input_path = tmp_path / "keys.csv"
    output_path = tmp_path / "keys.c"
    _ = input_path.write_text("00" * 28 + "\n", encoding="ascii")

    completed = run_converter(input_path, output_path)

    assert completed.returncode != 0
    assert "not a valid P-224 public X coordinate" in completed.stderr
    assert input_path.read_text(encoding="ascii").strip() not in completed.stderr
    assert not output_path.exists()


@pytest.mark.parametrize(
    ("contents", "expected_error"),
    [
        ("not-hexadecimal\n", "key is not hexadecimal"),
        ("01" * 27 + "\n", "expected exactly 28 bytes"),
        (f"{VALID_PUBLIC_X},00\n", "expected one 56-hex-digit value or 28 byte cells"),
    ],
)
def test_rejects_malformed_csv_without_disclosing_key_material(
    tmp_path: Path, contents: str, expected_error: str
) -> None:
    input_path = tmp_path / "keys.csv"
    output_path = tmp_path / "keys.c"
    _ = input_path.write_text(contents, encoding="ascii")

    completed = run_converter(input_path, output_path)

    assert completed.returncode != 0
    assert expected_error in completed.stderr
    assert contents.strip() not in completed.stderr
    assert not output_path.exists()


def test_rejects_duplicate_public_x_without_output(tmp_path: Path) -> None:
    input_path = tmp_path / "keys.csv"
    output_path = tmp_path / "keys.c"
    value = public_x(3)
    with input_path.open("w", encoding="ascii", newline="") as stream:
        csv.writer(stream).writerows([[value], [value]])

    completed = run_converter(input_path, output_path)

    assert completed.returncode != 0
    assert not output_path.exists()


def test_rejects_existing_output_without_overwriting_it(tmp_path: Path) -> None:
    input_path = tmp_path / "keys.csv"
    output_path = tmp_path / "keys.c"
    _ = input_path.write_text(public_x(4) + "\n", encoding="ascii")
    _ = output_path.write_text("existing output", encoding="ascii")

    completed = run_converter(input_path, output_path)

    assert completed.returncode != 0
    assert output_path.read_text(encoding="ascii") == "existing output"


def test_rejects_symlink_output_without_changing_target(tmp_path: Path) -> None:
    input_path = tmp_path / "keys.csv"
    target_path = tmp_path / "target.c"
    output_path = tmp_path / "keys.c"
    _ = input_path.write_text(public_x(5) + "\n", encoding="ascii")
    _ = target_path.write_text("target output", encoding="ascii")
    output_path.symlink_to(target_path)

    completed = run_converter(input_path, output_path)

    assert completed.returncode != 0
    assert target_path.read_text(encoding="ascii") == "target output"
