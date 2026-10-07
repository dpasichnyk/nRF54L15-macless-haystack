"""Merge per-beacon Macless device exports into one import file."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from deploy.report_fetch import JSON_LOADS, JsonValue
from tracking.crypto import ReportError, load_tags


class MergeError(ValueError):
    pass


def read_devices(path: Path) -> list[dict[str, JsonValue]]:
    data = JSON_LOADS(path.read_bytes())
    if not isinstance(data, list):
        raise MergeError(f"{path.name} must contain a list of devices")
    devices: list[dict[str, JsonValue]] = []
    for item in data:
        if not isinstance(item, dict):
            raise MergeError(f"{path.name} contains a device that is not an object")
        devices.append(item)
    return devices


def merge(sources: Sequence[Path]) -> list[dict[str, JsonValue]]:
    merged: dict[int, dict[str, JsonValue]] = {}
    for path in sources:
        for device in read_devices(path):
            identifier = device.get("id")
            if type(identifier) is not int:
                raise MergeError(f"{path.name} has a device without an integer id")
            existing = merged.get(identifier)
            if existing is None:
                merged[identifier] = device
            elif existing != device:
                raise MergeError(f"Device id {identifier} differs between sources")
    ordered = [merged[identifier] for identifier in sorted(merged)]
    try:
        _ = load_tags(json.dumps(ordered).encode())
    except ReportError as error:
        raise MergeError(str(error)) from error
    return ordered


def write(output: Path, devices: list[dict[str, JsonValue]]) -> None:
    payload = json.dumps(devices, separators=(",", ":")).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=output.parent, prefix=f".{output.name}.")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def summarize(devices: list[dict[str, JsonValue]]) -> str:
    lines: list[str] = []
    for device in devices:
        additional = device.get("additionalKeys")
        count = 1 + len(additional) if isinstance(additional, list) else 1
        lines.append(f"  id={device.get('id')} name={device.get('name')} keys={count}")
    return "\n".join(lines)


class Arguments(argparse.Namespace):
    output: Path = Path()
    sources: Sequence[Path] = ()


def main(argv: Sequence[str] | None = None) -> int:
    _ = os.umask(0o077)
    parser = argparse.ArgumentParser(
        description="Merge Macless device exports into one import file")
    _ = parser.add_argument("output", type=Path)
    _ = parser.add_argument("sources", type=Path, nargs="+")
    arguments = parser.parse_args(argv, namespace=Arguments())
    try:
        missing = [path.name for path in arguments.sources if not path.is_file()]
        if missing:
            raise MergeError(f"missing source files: {', '.join(missing)}")
        devices = merge(arguments.sources)
        write(arguments.output, devices)
    except (MergeError, OSError, ValueError) as error:
        print(f"merge failed: {error}", file=sys.stderr)
        return 1
    print(f"merged {len(devices)} device(s) into {arguments.output}")
    print(summarize(devices))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())