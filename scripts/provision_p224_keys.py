# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "cryptography==50.0.1",
#   "typer==0.27.2",
# ]
# ///

from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, NewType, TypedDict

import typer
from cryptography.hazmat.primitives.asymmetric import ec

PrivateScalar = NewType("PrivateScalar", bytes)
PublicX = NewType("PublicX", bytes)


class Device(TypedDict):
    name: str
    id: int
    colorComponents: list[int]
    privateKey: str
    icon: str
    isActive: bool
    additionalKeys: list[str]


@dataclass(frozen=True, slots=True)
class ProvisionedKey:
    private_scalar: PrivateScalar
    public_x: PublicX


def generate_key() -> ProvisionedKey:
    private_key = ec.generate_private_key(ec.SECP224R1())
    private_scalar = PrivateScalar(
        private_key.private_numbers().private_value.to_bytes(28, "big")
    )
    public_x = PublicX(private_key.public_key().public_numbers().x.to_bytes(28, "big"))
    return ProvisionedKey(private_scalar=private_scalar, public_x=public_x)


def stage_file(path: Path, content: bytes, mode: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    completed = False
    try:
        os.chmod(temporary_path, mode)
        with os.fdopen(descriptor, "wb") as stream:
            _ = stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        completed = True
    finally:
        if not completed:
            temporary_path.unlink(missing_ok=True)
    return temporary_path


def publish_pair(
    devices_output: Path,
    devices_content: bytes,
    public_keys_output: Path,
    public_keys_content: bytes,
) -> None:
    devices_temporary = stage_file(devices_output, devices_content, 0o600)
    public_keys_temporary: Path | None = None
    devices_published = False
    try:
        public_keys_temporary = stage_file(
            public_keys_output, public_keys_content, 0o644
        )
        os.link(devices_temporary, devices_output)
        devices_published = True
        os.link(public_keys_temporary, public_keys_output)
    except Exception:
        if devices_published:
            try:
                if os.path.samestat(devices_temporary.stat(), devices_output.lstat()):
                    devices_output.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
        raise
    finally:
        devices_temporary.unlink(missing_ok=True)
        if public_keys_temporary is not None:
            public_keys_temporary.unlink(missing_ok=True)


def provision(
    count: Annotated[int, typer.Option(min=1, max=50)],
    devices_output: Annotated[Path, typer.Option()],
    public_keys_output: Annotated[Path, typer.Option()],
) -> None:
    if devices_output.resolve() == public_keys_output.resolve():
        raise typer.BadParameter("output paths must differ")
    for output in (devices_output, public_keys_output):
        if output.exists() or output.is_symlink():
            raise typer.BadParameter(f"output already exists: {output}")

    keys = [generate_key() for _ in range(count)]
    private_keys = [
        base64.b64encode(key.private_scalar).decode("ascii") for key in keys
    ]
    device: Device = {
        "name": "nrf5-tag",
        "id": 1,
        "colorComponents": [0, 1, 0, 1],
        "privateKey": private_keys[-1],
        "icon": "",
        "isActive": True,
        "additionalKeys": private_keys[:-1],
    }
    devices_content = json.dumps([device], separators=(",", ":")).encode("ascii")
    public_keys_content = "\r\n".join(key.public_x.hex() for key in keys).encode(
        "ascii"
    )

    try:
        publish_pair(
            devices_output,
            devices_content,
            public_keys_output,
            public_keys_content,
        )
    except OSError as exc:
        raise typer.BadParameter(f"could not publish outputs: {exc}") from exc
    typer.echo(f"devices_json={devices_output}")
    typer.echo(f"public_x_csv={public_keys_output}")
    typer.echo(f"count={count}")


if __name__ == "__main__":
    typer.run(provision)
