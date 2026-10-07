from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from deploy.report_fetch import JSON_LOADS, JsonValue

APPLE_EPOCH: Final = 978307200
MAX_TAGS_BYTES: Final = 1024 * 1024
MAX_REPORTS_BYTES: Final = 4 * 1024 * 1024
P224_SCALAR_BYTES: Final = 28


class ReportError(ValueError):
    pass

@dataclass(frozen=True, slots=True)
class BeaconKey:
    report_id: str
    private_key: ec.EllipticCurvePrivateKey = field(repr=False)


@dataclass(frozen=True, slots=True)
class Tag:
    unique_id: str
    name: str
    keys: tuple[BeaconKey, ...]


@dataclass(frozen=True, slots=True)
class EncryptedReport:
    tag_id: str
    key_id: str
    payload: bytes = field(repr=False)

    @property
    def source_id(self) -> str:
        return hashlib.sha256(base64.b64decode(self.key_id) + self.payload).hexdigest()

    @property
    def timestamp(self) -> int:
        return int.from_bytes(self.payload[:4], "big") + APPLE_EPOCH


@dataclass(frozen=True, slots=True)
class Position:
    timestamp: int
    latitude: float
    longitude: float
    accuracy: int
    confidence: int
    status: int


def _decode_base64(value: str, message: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise ReportError(message) from error


def _beacon_key(value: str) -> BeaconKey:
    encoded_key = _decode_base64(value, "Tag private key is not valid base64")
    if len(encoded_key) != P224_SCALAR_BYTES:
        raise ReportError("Tag private key must be 28 bytes")
    try:
        private_key = ec.derive_private_key(int.from_bytes(encoded_key, "big"), ec.SECP224R1())
    except ValueError as error:
        raise ReportError("Tag private key is not a valid P-224 scalar") from error
    public_x = private_key.public_key().public_numbers().x.to_bytes(28, "big")
    report_id = base64.b64encode(hashlib.sha256(public_x).digest()).decode("ascii")
    return BeaconKey(report_id, private_key)


def _tag(data: dict[str, JsonValue]) -> Tag | None:
    identifier, name, active = data.get("id"), data.get("name"), data.get("isActive", True)
    if type(identifier) is not int or not 0 <= identifier <= 2_147_483_647:
        raise ReportError("Tag id must be an integer between 0 and 2147483647")
    if not isinstance(name, str) or not name or len(name) > 128:
        raise ReportError("Tag name must be a non-empty string up to 128 characters")
    if type(active) is not bool:
        raise ReportError("Tag isActive must be a boolean")
    if not active:
        return None
    private_key, additional_keys = data.get("privateKey"), data.get("additionalKeys", [])
    if not isinstance(private_key, str) or not isinstance(additional_keys, list):
        raise ReportError("Tag keys must be base64 strings")
    raw_keys = [private_key, *additional_keys]
    keys_by_id: dict[str, BeaconKey] = {}
    for raw_key in raw_keys:
        if not isinstance(raw_key, str):
            raise ReportError("Tag keys must be base64 strings")
        beacon_key = _beacon_key(raw_key)
        keys_by_id[beacon_key.report_id] = beacon_key
    if len(keys_by_id) > 50:
        raise ReportError("Tag must contain at most 50 distinct keys")
    return Tag(f"nrf5-tag-{identifier}", name, tuple(keys_by_id.values()))


def load_tags(body: bytes) -> tuple[Tag, ...]:
    if len(body) > MAX_TAGS_BYTES:
        raise ReportError("Tag file exceeds 1 MiB")
    try:
        data = JSON_LOADS(body)
    except (ValueError, RecursionError) as error:
        raise ReportError("Tag file is not valid JSON") from error
    if not isinstance(data, list):
        raise ReportError("Tag file must contain a list")
    tags: list[Tag] = []
    identifiers: set[str] = set()
    active_key_ids: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            raise ReportError("Each tag must be an object")
        tag = _tag(item)
        identifier = f"nrf5-tag-{item.get('id')}"
        if identifier in identifiers:
            raise ReportError("Tag ids must be unique")
        identifiers.add(identifier)
        if tag is None:
            continue
        for key in tag.keys:
            if key.report_id in active_key_ids:
                raise ReportError("Active tags must not share keys")
            active_key_ids.add(key.report_id)
        tags.append(tag)
    return tuple(tags)


def parse_reports(body: bytes, tag: Tag) -> tuple[EncryptedReport, ...]:
    if len(body) > MAX_REPORTS_BYTES:
        raise ReportError("Report body exceeds 4 MiB")
    try:
        data = JSON_LOADS(body)
    except (ValueError, RecursionError) as error:
        raise ReportError("Report body is not valid JSON") from error
    if not isinstance(data, dict) or data.get("statusCode") not in (200, "200"):
        raise ReportError("Report response was unsuccessful")
    results = data.get("results")
    if not isinstance(results, list):
        raise ReportError("Report response results must be a list")
    key_ids = {key.report_id for key in tag.keys}
    reports: list[EncryptedReport] = []
    for item in results:
        if not isinstance(item, dict):
            raise ReportError("Report entry must be an object")
        key_id, payload = item.get("id"), item.get("payload")
        if not isinstance(key_id, str) or key_id not in key_ids or not isinstance(payload, str):
            raise ReportError("Report entry has an unexpected key or payload")
        decoded = _decode_base64(payload, "Report payload is not valid base64")
        if len(decoded) < 4:
            raise ReportError("Report payload has no timestamp")
        reports.append(EncryptedReport(tag.unique_id, key_id, decoded))
    return tuple(reports)


def decrypt_report(report: EncryptedReport, key: BeaconKey, now: int) -> Position:
    if report.key_id != key.report_id:
        raise ReportError("Report key does not match decryption key")
    if len(report.payload) not in (88, 89):
        raise ReportError("Report payload has an unsupported length")
    payload = report.payload if len(report.payload) == 88 else report.payload[:4] + report.payload[5:]
    try:
        ephemeral = payload[5:62]
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP224R1(), ephemeral)
        shared_key = key.private_key.exchange(ec.ECDH(), public_key)
        symmetric_key = hashlib.sha256(shared_key + b"\0\0\0\1" + ephemeral).digest()
        plaintext = AESGCM(symmetric_key[:16]).decrypt(symmetric_key[16:], payload[62:88], None)
    except InvalidTag as error:
        raise ReportError("Report authentication failed") from error
    except ValueError as error:
        raise ReportError("Report cryptographic data is invalid") from error
    if len(plaintext) != 10:
        raise ReportError("Report plaintext has an invalid length")
    latitude = int.from_bytes(plaintext[:4], "big", signed=True) / 10_000_000
    longitude = int.from_bytes(plaintext[4:8], "big", signed=True) / 10_000_000
    timestamp = int.from_bytes(payload[:4], "big") + APPLE_EPOCH
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ReportError("Report coordinates are outside valid bounds")
    if not APPLE_EPOCH <= timestamp <= now + 300:
        raise ReportError("Report timestamp is outside the allowed range")
    return Position(timestamp, latitude, longitude, plaintext[8], payload[4], plaintext[9])
