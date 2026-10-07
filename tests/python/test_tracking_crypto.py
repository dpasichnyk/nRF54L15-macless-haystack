import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Literal

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from tracking.crypto import (
    APPLE_EPOCH,
    BeaconKey,
    EncryptedReport,
    ReportError,
    decrypt_report,
    load_tags,
    parse_reports,
)

NOW = APPLE_EPOCH + 1_000_000


@dataclass(frozen=True, slots=True)
class ReportFixture:
    report: EncryptedReport
    key: BeaconKey
    latitude: float
    longitude: float


def private_key_bytes(value: int) -> str:
    return base64.b64encode(value.to_bytes(28, "big")).decode("ascii")


def report_id(private_key: ec.EllipticCurvePrivateKey) -> str:
    public_x = private_key.public_key().public_numbers().x.to_bytes(28, "big")
    return base64.b64encode(hashlib.sha256(public_x).digest()).decode("ascii")


def test_scalar_one_matches_known_advertisement_x_hash() -> None:
    public_x = bytes.fromhex("b70e0cbd6bb4bf7f321390b94a03c1d356c21122343280d6115c1d21")
    tag, = load_tags(json.dumps([{"id": 1, "name": "tag", "privateKey": private_key_bytes(1)}]).encode())
    assert tag.keys[0].report_id == base64.b64encode(hashlib.sha256(public_x).digest()).decode()


def test_full_rotation_table_imports_fifty_distinct_keys() -> None:
    tag, = load_tags(json.dumps([{
        "id": 1, "name": "tag", "privateKey": private_key_bytes(50),
        "additionalKeys": [private_key_bytes(value) for value in range(1, 50)],
    }]).encode())
    assert len(tag.keys) == 50
    assert len({key.report_id for key in tag.keys}) == 50


def encrypted_fixture(private_value: int, negative: bool = False) -> ReportFixture:
    private_key = ec.derive_private_key(private_value, ec.SECP224R1())
    key = BeaconKey(report_id(private_key), private_key)
    latitude, longitude = (-12.3456789, -98.7654321) if negative else (12.3456789, 98.7654321)
    plaintext = (
        round(latitude * 10_000_000).to_bytes(4, "big", signed=True)
        + round(longitude * 10_000_000).to_bytes(4, "big", signed=True)
        + bytes((7, 9))
    )
    ephemeral_private = ec.derive_private_key(private_value + 100, ec.SECP224R1())
    ephemeral = ephemeral_private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    symmetric_key = hashlib.sha256(
        ephemeral_private.exchange(ec.ECDH(), private_key.public_key()) + b"\0\0\0\1" + ephemeral,
    ).digest()
    ciphertext = AESGCM(symmetric_key[:16]).encrypt(symmetric_key[16:], plaintext, None)
    payload = (NOW - APPLE_EPOCH).to_bytes(4, "big") + bytes((3,)) + ephemeral + ciphertext
    return ReportFixture(EncryptedReport("nrf5-tag-1", key.report_id, payload), key, latitude, longitude)


def test_decrypts_authenticated_88_and_89_byte_reports_with_signed_coordinates() -> None:
    fixture = encrypted_fixture(1, negative=True)

    position = decrypt_report(fixture.report, fixture.key, NOW)
    extended = EncryptedReport("nrf5-tag-1", fixture.key.report_id, fixture.report.payload[:4] + b"x" + fixture.report.payload[4:])

    assert (position.latitude, position.longitude, position.confidence, position.accuracy, position.status) == (
        fixture.latitude, fixture.longitude, 3, 7, 9,
    )
    assert decrypt_report(extended, fixture.key, NOW).latitude == fixture.latitude


def test_load_tags_and_parse_reports_include_all_rotated_keys() -> None:
    first, second = encrypted_fixture(2), encrypted_fixture(3)
    body = json.dumps([{
        "id": 1, "name": "tag", "privateKey": private_key_bytes(2),
        "additionalKeys": [private_key_bytes(3)],
    }, {
        "id": 2, "name": "inactive", "privateKey": private_key_bytes(4), "isActive": False,
    }]).encode()

    tag, = load_tags(body)
    reports = parse_reports(json.dumps({"statusCode": 200, "results": [
        {"id": first.key.report_id, "payload": base64.b64encode(first.report.payload).decode()},
        {"id": second.key.report_id, "payload": base64.b64encode(second.report.payload).decode()},
    ]}).encode(), tag)

    assert {report.key_id for report in reports} == {first.key.report_id, second.key.report_id}
    assert reports[0].timestamp == NOW
    assert reports[0].source_id == hashlib.sha256(base64.b64decode(reports[0].key_id) + reports[0].payload).hexdigest()
    assert {decrypt_report(report, next(key for key in tag.keys if key.report_id == report.key_id), NOW).status for report in reports} == {9}


@pytest.mark.parametrize("mutation", ["wrong-key", "tamper", "invalid-point", "unsupported-length", "future"])
def test_decrypt_rejects_integrity_and_format_failures(
    mutation: Literal["wrong-key", "tamper", "invalid-point", "unsupported-length", "future"],
) -> None:
    fixture = encrypted_fixture(4)
    report, key = fixture.report, fixture.key
    match mutation:
        case "wrong-key":
            key = encrypted_fixture(5).key
        case "tamper":
            report = EncryptedReport(report.tag_id, report.key_id, report.payload[:-1] + bytes([report.payload[-1] ^ 1]))
        case "invalid-point":
            report = EncryptedReport(report.tag_id, report.key_id, report.payload[:5] + b"\x04" + b"\0" * 56 + report.payload[62:])
        case "unsupported-length":
            report = EncryptedReport(report.tag_id, report.key_id, report.payload[:-1])
        case "future":
            future = (NOW + 301 - APPLE_EPOCH).to_bytes(4, "big")
            report = EncryptedReport(report.tag_id, report.key_id, future + report.payload[4:])

    with pytest.raises(ReportError):
        _ = decrypt_report(report, key, NOW)


@pytest.mark.parametrize("record", [
    {"id": 1, "name": "tag", "privateKey": "bad"},
    {"id": True, "name": "tag", "privateKey": private_key_bytes(6)},
    {"id": 1, "name": "", "privateKey": private_key_bytes(6)},
    {"id": 1, "name": "tag", "privateKey": private_key_bytes(0)},
])
def test_load_tags_rejects_invalid_imports(record: dict[str, int | str | bool]) -> None:
    with pytest.raises(ReportError):
        _ = load_tags(json.dumps([record]).encode())


def test_load_tags_rejects_duplicate_ids_and_active_key_reuse() -> None:
    duplicate_ids = [
        {"id": 1, "name": "one", "privateKey": private_key_bytes(7)},
        {"id": 1, "name": "two", "privateKey": private_key_bytes(8)},
    ]
    shared_key = [
        {"id": 1, "name": "one", "privateKey": private_key_bytes(9)},
        {"id": 2, "name": "two", "privateKey": private_key_bytes(9)},
    ]

    for body in (duplicate_ids, shared_key):
        with pytest.raises(ReportError):
            _ = load_tags(json.dumps(body).encode())


@pytest.mark.parametrize("body", [
    b'{"statusCode":200,"results":[{"id":"wrong","payload":"YQ=="}]}',
    b'{"statusCode":200,"results":[{"id":"wrong","payload":"bad"}]}',
    b'{"statusCode":500,"results":[]}',
])
def test_parse_reports_rejects_malformed_entries(body: bytes) -> None:
    tag, = load_tags(json.dumps([{"id": 1, "name": "tag", "privateKey": private_key_bytes(10)}]).encode())

    with pytest.raises(ReportError):
        _ = parse_reports(body, tag)


def test_parse_reports_rejects_non_base64_payload_for_matching_key() -> None:
    tag, = load_tags(json.dumps([{"id": 1, "name": "tag", "privateKey": private_key_bytes(11)}]).encode())
    body = json.dumps({"statusCode": 200, "results": [{"id": tag.keys[0].report_id, "payload": "bad"}]}).encode()

    with pytest.raises(ReportError):
        _ = parse_reports(body, tag)
