import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "tests" / "firmware" / "check_profile.cmake"
COMMON = (
    "BT", "BT_BROADCASTER", "HW_STACK_PROTECTION", "TICKLESS_KERNEL",
)
DEVELOPMENT = (
    "ASSERT", "DEBUG_OPTIMIZATIONS", "LOG", "LOG_BACKEND_RTT",
    "LOG_BACKEND_RTT_MODE_DROP", "USE_SEGGER_RTT", "RTT_CONSOLE",
    "CONSOLE", "PRINTK", "NCS_BOOT_BANNER", "LOG_MODE_DEFERRED",
)
SETTINGS = (
    "BT_ID_MAX=2", "ADV_INTERVAL_MS=5000", "ADVERTISE_WINDOW_S=1800", "SLEEP_S=0",
)
DEVELOPMENT_SETTINGS = (
    "SEGGER_RTT_BUFFER_SIZE_UP=4096", "LOG_BACKEND_RTT_MESSAGE_SIZE=256",
    "COMMON_LIBC_MALLOC_ARENA_SIZE=-1",
)


@pytest.mark.parametrize("profile", ["production", "development"])
@pytest.mark.parametrize("violation", ["", "SERIAL=y", "BT_OBSERVER=y", "LOG=y"])
def test_profile_guard_rejects_unwanted_features(
    tmp_path: Path, profile: str, violation: str,
) -> None:
    enabled = COMMON + (
        DEVELOPMENT if profile == "development" else (
            "SIZE_OPTIMIZATIONS", "RAM_POWER_DOWN_LIBRARY", "NRF_FORCE_RAM_ON_REBOOT",
        )
    )
    entries = [f"CONFIG_{name}=y" for name in enabled]
    entries.extend(f"CONFIG_{setting}" for setting in SETTINGS)
    if profile == "development":
        entries.extend(f"CONFIG_{setting}" for setting in DEVELOPMENT_SETTINGS)
    else:
        entries.append("CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE=0")
    if violation:
        entries.append(f"CONFIG_{violation}")
    (tmp_path / "zephyr").mkdir()
    _ = (tmp_path / "zephyr" / ".config").write_text("\n".join(entries))

    result = subprocess.run(
        ["cmake", f"-DBUILD_DIR={tmp_path}", f"-DPROFILE={profile}", "-P", str(CHECK)],
        capture_output=True, text=True, check=False,
    )

    allowed = not violation or (profile == "development" and violation == "LOG=y")
    assert (result.returncode == 0) == allowed, result.stdout + result.stderr


def test_development_rejects_small_rtt_buffer(tmp_path: Path) -> None:
    entries = [f"CONFIG_{name}=y" for name in COMMON + DEVELOPMENT]
    entries.extend(f"CONFIG_{setting}" for setting in SETTINGS + DEVELOPMENT_SETTINGS)
    (tmp_path / "zephyr").mkdir()
    _ = (tmp_path / "zephyr" / ".config").write_text(
        "\n".join(entries).replace("SEGGER_RTT_BUFFER_SIZE_UP=4096", "SEGGER_RTT_BUFFER_SIZE_UP=1024")
    )
    result = subprocess.run(
        ["cmake", f"-DBUILD_DIR={tmp_path}", "-DPROFILE=development", "-P", str(CHECK)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0


@pytest.mark.parametrize("profile", ["unknown", "production development", "%"])
def test_make_rejects_invalid_profile(profile: str) -> None:
    result = subprocess.run(
        ["make", "-n", "build", f"PROFILE={profile}"], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0


def test_development_monitor_uses_development_directory() -> None:
    result = subprocess.run(
        ["make", "-n", "monitor"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    )
    assert str(ROOT / "build-development") in result.stdout
    assert str(ROOT / "build-production") not in result.stdout


def dry_run(*arguments: str) -> str:
    result = subprocess.run(
        ["make", "-n", *arguments], cwd=ROOT,
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def test_default_tag_keeps_the_original_single_tag_paths() -> None:
    output = dry_run("keys")

    assert f"{ROOT / 'src/keys.c'}" in output
    assert "nrf5-tag_devices.json" in output
    assert "src/keys_" not in output.replace(f"{ROOT / 'src/keys.c'}", "")


@pytest.mark.parametrize("command", ["build", "flash"])
def test_tagged_build_uses_its_own_key_table_and_directory(command: str) -> None:
    output = dry_run(command, "TAG=b")
    keys = ROOT / "src" / "keys_b.c"
    directory = ROOT / "build-production-b"

    assert f'-DBEACON_KEYS_C="{keys}"' in output
    assert f'"{directory}"' in output


def test_untagged_build_keeps_default_paths() -> None:
    output = dry_run("build")
    keys = ROOT / "src" / "keys.c"
    directory = ROOT / "build-production"

    assert f'-DBEACON_KEYS_C="{keys}"' in output
    assert f'"{directory}"' in output
    assert "keys_b.c" not in output
    assert "build-production-b" not in output


def test_tagged_development_build_forwards_the_tag() -> None:
    output = dry_run("build-dev", "TAG=b")
    directory = ROOT / "build-development-b"

    assert "PROFILE=development" in output
    assert f'"{directory}"' in output
    assert f'"{ROOT / "build-development"}"' not in output


def test_keys_for_two_tags_produce_distinct_outputs() -> None:
    first = dry_run("keys")
    second = dry_run("keys", "TAG=b", "DEVICE_ID=2")

    assert "nrf5-tag_b_devices.json" in second
    assert "src/keys_b.c" in second
    assert "--device-id \"2\"" in second
    assert first != second


def test_import_merges_every_generated_device_export() -> None:
    output = dry_run("import")

    assert "-m tracking.devices" in output
    assert "nrf5-tag_import.json" in output
