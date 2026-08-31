#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["cryptography==50.0.1"]
# ///
"""Convert a CSV of hexadecimal P-224 public-X keys to src/keys.c.

Input format: one key per row, either a single 56-hex-digit field or a row of
28 hexadecimal byte fields. The script never prints key material.
"""

import argparse
import csv
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec


class Arguments(argparse.Namespace):
    input: Path = Path()
    output: Path = Path()


def parse_key(row: list[str], line: int) -> bytes:
    if len(row) == 1:
        value = row[0].strip()
    elif len(row) == 28:
        value = "".join(part.strip() for part in row)
    else:
        raise ValueError(
            f"line {line}: expected one 56-hex-digit value or 28 byte cells"
        )
    try:
        key = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"line {line}: key is not hexadecimal") from exc
    if len(key) != 28:
        raise ValueError(f"line {line}: expected exactly 28 bytes")
    try:
        _ = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP224R1(), b"\x02" + key)
    except ValueError as exc:
        raise ValueError(f"line {line}: not a valid P-224 public X coordinate") from exc
    return key


def render_keys(keys: list[bytes]) -> bytes:
    lines = [
        '#include <stdint.h>\n#include "keys.h"\n',
        "const uint8_t beacon_keys[][BEACON_KEY_BYTES] = {",
    ]
    lines.extend(
        "    {" + ", ".join(f"0x{byte:02x}" for byte in key) + "}," for key in keys
    )
    lines.extend(
        [
            "};\n",
            "const size_t beacon_key_count = sizeof(beacon_keys) / sizeof(beacon_keys[0]);",
            "#ifdef CONFIG_N_KEYS",
            "_Static_assert(sizeof(beacon_keys) / sizeof(beacon_keys[0]) == CONFIG_N_KEYS,",
            '               "generated beacon key count does not match CONFIG_N_KEYS");',
            "#endif",
        ]
    )
    return ("\n".join(lines) + "\n").encode("ascii")


def write_new_atomically(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("input", type=Path)
    _ = parser.add_argument("output", type=Path)
    args = Arguments()
    _ = parser.parse_args(namespace=args)

    keys: list[bytes] = []
    try:
        with args.input.open(newline="") as stream:
            for line, row in enumerate(csv.reader(stream), 1):
                if not row or not any(part.strip() for part in row):
                    continue
                keys.append(parse_key(row, line))
    except ValueError as exc:
        parser.error(str(exc))
    if not keys:
        parser.error("input contains no keys")
    if len(set(keys)) != len(keys):
        parser.error("input contains duplicate keys")

    if args.output.exists() or args.output.is_symlink():
        parser.error(f"output already exists: {args.output}")
    try:
        write_new_atomically(args.output, render_keys(keys))
    except OSError as exc:
        parser.error(f"could not publish output: {exc}")


if __name__ == "__main__":
    main()
