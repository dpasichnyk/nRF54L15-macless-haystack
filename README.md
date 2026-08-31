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

### 2. Build and flash
Connect the board, then run:

```sh
make flash
```

This builds with NCS `v3.2.1` and flashes the CPUAPP image through OpenOCD with image verification enabled.

### 3. Register Apple access
```sh
make setup
```

The command is interactive. It asks for the Apple ID, password, and SMS 2FA
code, then starts the endpoint. The saved token is `deploy/endpoint/auth.json`.

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

The endpoint returns encrypted Apple reports. The client uses the private devices JSON to decrypt them. An empty result does not by itself show that the beacon is faulty.

## Operations
| Command | Purpose |
| --- | --- |
| `make keys` | Generate the private import and firmware public key table. |
| `make help` | List the supported commands. |
| `make flash` | Build and verified-flash the firmware. |
| `make setup` | Register Apple credentials and start the endpoint. |
| `make status` | Show Docker service status. |
| `make logs` | Follow Docker service logs. |
| `make up` | Start an existing registered deployment. |
| `make down` | Stop services without deleting their data. |
| `make reset-auth` | Remove only the saved Apple token. |
| `make test` | Run firmware and deployment checks. |

After `make reset-auth`, run `make setup` to register again. Anisette state and
key files are preserved. `make setup` refuses to run while the auth file
already exists.

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
The console is UART20 at 115200 baud. Connect a 3.3 V USB-UART adapter to
P1.09 for TX and P1.08 for RX. The CMSIS-DAP USB modem is not the text console
used by this board configuration.

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
