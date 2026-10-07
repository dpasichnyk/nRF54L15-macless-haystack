# nRF54L15 Macless-Haystack beacon

This project turns a Seeed XIAO nRF54L15 into a broadcaster-only beacon for OpenHaystack and Macless-Haystack.

It is not an Apple-certified accessory and cannot be paired in the native Find
My app. Report retrieval uses unofficial Apple APIs. Reports, coverage, and
delivery are not guaranteed.

## Supported hardware
The only supported and tested target is the Seeed XIAO nRF54L15 CPUAPP core,
using Zephyr target `xiao_nrf54l15/nrf54l15/cpuapp`.

Other boards are not implemented or tested. Do not assume that another nRF54L
board, core, or programmer will work.

## Requirements
- XIAO nRF54L15 and a USB cable
- Nordic nRF Connect SDK `v3.2.1`, launched through `nrfutil`
- `uv`
- Docker with Docker Compose
- GNU Make
- An Apple ID that can complete SMS two-factor authentication
- A Macless-Haystack client for importing the generated devices JSON

Local regression tests also require CMake, a C compiler with AddressSanitizer/
UndefinedBehaviorSanitizer support, and Tcl (`tclsh`). The SDK remains pinned to
the hardware-verified NCS `v3.2.1`; builds do not silently upgrade it.

## Quick start
### 1. Generate keys
```sh
make keys
```

This creates 50 P-224 key pairs, a private devices JSON import, and the public
key table used by the firmware. At the default 30-minute epoch, the identity
wraps after 25 hours. The private import is stored at
`~/.local/share/nrf5-tag/nrf5-tag_devices.json`.

Import this JSON into Macless-Haystack and keep it private. The generated
`src/keys.c` contains public X coordinates and is ignored by Git. `make keys`
refuses to overwrite existing outputs.

`make keys` also merges every generated device export into a single import file
at `~/.local/share/nrf5-tag/nrf5-tag_import.json`. That merged file is what the
client and the collector consume, so it is the only file you need to import or
mount. `make import` rebuilds it without regenerating keys.

### Tracking several beacons
Each physical beacon needs its own key table. Beacons that share a key table
are indistinguishable to Apple and appear as one device.

```sh
make keys TAG=b DEVICE_ID=2       # independent 50-key table for a second beacon
make flash TAG=b                   # build and flash it to that board
```

`TAG` selects an isolated slug, so nothing is shared or overwritten:

| Artifact | First beacon | Second beacon (`TAG=b`) |
| --- | --- | --- |
| Firmware key table | `src/keys.c` | `src/keys_b.c` |
| Private device export | `nrf5-tag_devices.json` | `nrf5-tag_b_devices.json` |
| Build directory | `build-production/` | `build-production-b/` |

`DEVICE_ID` must be unique; the collector and the map use it as the device
identity. After generating keys, run `make import` (or `make keys`, which calls
it) so the merged import contains every beacon, then re-run `make tracking-up`
to register new tags. Import the same merged file into the Macless-Haystack
client.

To rebuild the original beacon later, use the default untagged commands:
`make keys` and `make flash`.

### 2. Build and flash
Connect the board, then run:

```sh
make flash
```

This builds with NCS `v3.2.1` and flashes the CPUAPP image through OpenOCD with
image verification enabled. The local loader commits the nRF54L15 RRAM write
buffer before reset so a partial final write is not lost.

### 3. Register Apple access
```sh
make setup
```

Setup waits for Anisette to return usable headers before registration, with
12 attempts and a five-second socket timeout per request. If startup fails,
registration does not proceed. Invalid readiness URLs fail without retrying;
responses must be valid JSON and no larger than 64 KiB. The command is
interactive: it asks for the Apple ID, password, and SMS 2FA code, then starts
the endpoint. The saved token is `deploy/endpoint/auth.json`.

The file is kept with mode `0600` and is ignored by Git. The endpoint is
available from the host at `http://127.0.0.1:6176`. Inside the container it
binds to `0.0.0.0`; Docker exposes it only on the host loopback address.

### 4. Check the services
```sh
make status
```

Import the devices JSON into your Macless-Haystack client before expecting it
to decrypt reports.

## How it works
The firmware has one job: advertise.

- The beacon sends a legacy Bluetooth advertisement every 5 seconds.
- Its identity rotates through 50 keys on a 30-minute epoch.
- Rotation briefly stops advertising, resets the identity, and starts again.
- Rotation state exists only in RAM. It is not stored in GPREGRET.
- The application does not enter system-off or add a powered-down interval
  between key epochs; Zephyr only blocks the application thread while advertising.
- It only broadcasts. It does not scan, connect, advertise a name, or send scan
  responses.
- Production builds disable serial logging and turn off the unused IMU and
  microphone supply. The controller remains active for scheduled advertisements;
  the CPU uses System ON idle between work, not System OFF.
- The RF switch is explicitly powered on and selects the onboard ceramic
  antenna. An external antenna requires a different select setting.

The advertising window must be positive and at least as long as the configured
advertising interval. Both window and optional sleep durations are limited to
65,535 seconds to keep timeout arithmetic bounded. These are nominal intervals,
not guarantees of an on-air packet or a network sighting.

The endpoint returns encrypted Apple reports. The client uses the private devices JSON to decrypt them. An empty result does not by itself show that the beacon is faulty.

### Report retrieval and rotation
The endpoint sends one Apple search entry per key, grouped into a single HTTP
request. Putting all 50 keys into one search entry can omit newer reports; this
was reproduced against the live service. There is no need to change the firmware
or regenerate keys to fix that query behavior.

Results are sorted newest-first and deduplicated by key and encrypted payload,
not timestamp alone. Distinct sightings in the same second are preserved.
The endpoint queries every requested key, rather than guessing the active key
from the time: reboot restarts the firmware's RAM-only rotation at key zero.

Successful, validated responses are cached in memory for 30 seconds, for at most
four distinct key sets. The requested time window is applied on every refresh,
including cache hits. The cache contains encrypted reports, not private keys,
and disappears when the endpoint restarts. Expired data is not returned as a
successful fallback after a failed fetch.

Requests accept 1–50 distinct base64 SHA-256 key IDs and an integer `days` from
1–31 (default 7). Request bodies are capped at 64 KiB and upstream responses at
4 MiB. Apple requests have five-second connection and fifteen-second socket-read
timeouts. Timeouts, empty bodies and server errors get at most one retry;
authentication failures and rate limits are not retried. These are socket
timeouts, not an absolute end-to-end deadline against a continuously streaming
server. Apple still controls report availability and historical retention.

Client errors return HTTP 400/413, unavailable or rate-limited upstream services
return 503, upstream/authentication/protocol failures return 502, and reported
upstream timeouts return 504. Errors have JSON bodies; a failed fetch is not
presented as a successful empty report list.

After updating the endpoint code, preserve existing authentication and rebuild:

```sh
docker compose up -d --build --no-deps endpoint
```

## Operations
For persistent history, route playback, and geofences, use the optional
[Traccar tracking stack](TRACKING.md). It reuses this endpoint and the existing
keys; no firmware changes or second Apple login are required.

| Command | Purpose |
| --- | --- |
| `make keys` | Generate the private import and firmware public key table. |
| `make keys TAG=b DEVICE_ID=2` | Generate an independent key table for another beacon. |
| `make import` | Merge every device export into the single import file. |
| `make help` | List the supported commands. |
| `make build` | Build and verify the production configuration, without flashing. |
| `make build-dev` | Build and verify the development configuration, without flashing. |
| `make flash` | Build and verified-flash production firmware. |
| `make flash-dev` | Build and verified-flash development firmware. |
| `make monitor` | Reset the development firmware and stream RTT logs over USB. |
| `make setup` | Register Apple credentials and start the endpoint. |
| `make status` | Show Docker service status. |
| `make logs` | Follow Docker service logs. |
| `make up` | Start an existing registered deployment. |
| `make down` | Stop services without deleting their data. |
| `make reset-auth` | Remove only the saved Apple token. |
| `make test` | Run firmware and deployment checks. |
| `make test-firmware` | Run sanitized C/Tcl tests, Python tests, lint, and type checks. |
| `make test-deploy` | Run readiness and Docker image/Compose contract checks. |

After `make reset-auth`, run `make setup` to register again. Anisette state and
key files are preserved. `make setup` refuses to run while the auth file
already exists.

## Production and development profiles

| Property | Production | Development |
| --- | --- | --- |
| Build directory | `build-production/` | `build-development/` |
| Optimization | Size (`-Os`) | Debug-friendly (`-Og`) |
| Logs and console | Disabled | Deferred RTT logs over USB/SWD |
| Software assertions | SDK production default: disabled | Enabled |
| Hardware stack protection | Enabled | Enabled |
| Unused CPUAPP RAM | Complete unused sections powered down | Kept powered for debugging |
| Libc malloc arena | Disabled; firmware uses static pools | SDK default |
| UART | Disabled | Disabled |
| Advertising/key timing | 5 seconds / 30 minutes | Same |
| RF switch / unused sensor supply | Onboard antenna / off | Same |

The profiles share the firmware implementation, public key table, and radio
behavior. Development does not secretly accelerate rotation or use example keys.
Normal RTT logs are dropped if the host is absent or the buffer is full, rather
than blocking advertising. Fatal/panic logging may block for debugging. The
development build and attached debugger are not suitable for power measurements.

Production powers down only complete RAM sections between the linked image end
and CPUAPP's devicetree boundary. It leaves the section overlapping FLPR memory
and memory outside CPUAPP untouched. The current image releases 128 KiB; the
hardware mask and software-reboot recovery were verified on the board. This is
not a measured current reduction. Adding dynamic allocation requires revisiting
the heap and RAM-power configuration together.

Every supported build checks the resolved Kconfig, not only configuration source
files. CI compiles both profiles using example keys, runs the same profile gate,
and checks host and deployment behavior. CI compile-test images are not release
images. CI actions and container images remain pinned; workflow permissions are
read-only. Local tests use a fresh temporary C build directory per invocation.

`PROFILE=production` is the default. `PROFILE=development` is available directly
as well as through the `-dev` targets. `NCS_DIR` can override the SDK workspace
location; `BUILD_DIR` can override the output directory. Use the same custom
`BUILD_DIR` for a development flash and its monitor command. `TAG` selects an
independent key table and build directory for an additional beacon; without it,
the original single-beacon paths are used unchanged.

## Troubleshooting
### `make flash` says that keys are missing
Run `make keys` first. The build requires generated `src/keys.c`; the private
JSON import is separate and must also be kept for report decryption.

### `make keys` refuses to overwrite a file
The command found an existing output. Keep a secure backup, then remove or
move only the output you intentionally want to regenerate.

To replace an older one-key setup, back up and move the devices JSON,
`public-x.csv`, and `src/keys.c` together. Run `make keys`, import the new JSON,
and flash the newly generated firmware.

### Two beacons appear as one device
They share a key table. Generate a separate table with
`make keys TAG=<slug> DEVICE_ID=<unique id>`, flash that build to the second
board, then run `make import` and `make tracking-up`. The merged import file
must list every beacon; each device `id` must be unique.

### `make setup` says that authentication already exists
The existing token is at `deploy/endpoint/auth.json`. Use `make up` to keep it.
To replace it, run:

```sh
make reset-auth
make setup
```

### SMS 2FA fails during setup
Leave `make setup` waiting at its first code prompt. In a private browser window,
sign in to iCloud and choose **Didn't Get a Code?** then **Text Message**. Enter
that fresh SMS code in the terminal. The endpoint includes the local
[Macless-Haystack PR #226 idmsa fix](https://github.com/dchristl/macless-haystack/pull/226).

### Reports are empty
Reports depend on Apple network sightings and an unofficial service. Check
`make status`, follow `make logs`, and confirm that the devices JSON was
imported into Macless-Haystack. Empty reports are not proof of a firmware or
radio failure, and report delivery is not promised.

### The board does not appear to flash correctly
The normal path uses OpenOCD image verification. Run `make flash` again with
the board connected. The verified path was tested with the XIAO CMSIS-DAP.

### Runtime logs are needed
Production firmware has no console. With the board connected over USB, run:

```sh
make flash-dev
make monitor
```

This uses the onboard CMSIS-DAP probe and OpenOCD RTT, tested on the actual XIAO.
No external USB-UART adapter is needed. Run the monitor from an interactive
terminal; it resets the target and may display buffered logs from before reset.
Ctrl+C stops the monitor and its OpenOCD server. Only run it against the matching
development image. Restore the low-power production build afterwards:

```sh
make flash
```

### Measuring power
Software configuration is not a battery-life measurement. Measure the production
image on the intended supply with the debugger and USB-UART disconnected. Check
idle current, advertising pulses, and a complete key-rotation boundary. Board
regulators, the debugger, and reset-time pin states can contribute independently
of the application. No current-consumption or battery-life figure is guaranteed.

## Security
Treat `~/.local/share/nrf5-tag/nrf5-tag_devices.json` and
`deploy/endpoint/auth.json` as secrets. Do not commit them or expose port 6176
to a network. Do not put Apple credentials in
`deploy/endpoint/config.ini`. The endpoint is host-local by default.

## References
- [OpenHaystack](https://github.com/seemoo-lab/openhaystack)
- [Macless-Haystack](https://github.com/dchristl/macless-haystack)
- [Macless-Haystack protocol commit](https://github.com/dchristl/macless-haystack/commit/0bda271b8bd0cc37194dfba1845cd48954cba4cc)
- [OpenHaystack Zephyr commit](https://github.com/koenvervloesem/openhaystack-zephyr/commit/86c4ea5219602eac8a7a800eccf4164ba865aa6e)
