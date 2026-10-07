# Persistent tracking

This optional stack belongs in the same repository because it shares the beacon
key format, corrected Apple endpoint, and deployment workflow. It does not change
firmware or replace the existing Macless-Haystack UI.

```text
Apple reports -> existing endpoint -> collector -> private SQLite history/outbox
                                              -> Traccar -> PostgreSQL -> browser
```

## Start

First complete the normal `make setup` flow. Keep the existing private devices
JSON at `~/.local/share/nrf5-tag/nrf5-tag_devices.json`, or set `DEVICES_JSON` to
another Macless-Haystack import file. Then:

```sh
make tracking-up
```

Open **http://127.0.0.1:8082**. The generated owner login is in
`.tracking/admin.json`; read it locally and keep it private. There is no shared
default password. `TRACKING_PORT` can change the localhost UI port.

To see the collected track, open **Reports → Replay**, choose the tag and period,
and press **Show**. Use **Reports → Positions** for the complete point table.
The default Combined report emphasizes events/stops and is not the full point list.

The setup creates a restricted collector account and virtual devices with random
192-bit ingestion identifiers. The logical `nrf5-tag-<id from the import file>`
is stored separately in a device attribute. It reuses existing accounts and devices on
subsequent runs and refuses to replace missing/inconsistent credentials silently.
Public user registration is disabled after first-user creation.

Only the web UI is published, on localhost. Traccar also exposes a protocol proxy
through its web port, so keep device identifiers private. The OsmAnd ingestion port and
PostgreSQL are not published. The collector cannot administer Traccar. Existing
containers outside this project are not modified.

## Behavior

- Every device in the merged import file is tracked, including `privateKey` and
  `additionalKeys` for each. One tag becomes one Traccar device, so several
  beacons stay separate. No clock-based guess about the active firmware key is
  needed, and rebooted beacons restart at their own key zero.
- Polling runs every 60 seconds, with bounded error backoff. Set
  `TRACKING_POLL_SECONDS` to 30–3600 seconds if needed.
- Every available report is stored by tag and a digest of its key ID plus
  encrypted payload. Different reports in the same second are retained.
- P-224 ECDH and AES-GCM authentication must succeed before coordinates can be
  forwarded. Unsupported or invalid reports are retained as rejected records.
- SQLite commits raw report data and the decoded position/outbox state together.
  Traccar downtime does not stop report collection. Pending positions are sent
  oldest-first when it becomes available again.
- A Traccar HTTP acknowledgement alone is insufficient: the collector checks
  the stored position through the read-only API before marking delivery complete.
  Replays check the report ID first. This reduces duplicates but is not a formal
  exactly-once distributed transaction.
- Late reports are accepted with their original timestamps. No distance,
  stationary-point, or timestamp-only duplicate filtering is enabled here.
- Collection continues without an open browser. There is no automatic history
  deletion. Disk space and backups remain the operator's responsibility.

In Traccar, select the tag and use Positions or Replay with the appropriate
date range. Identical coordinates overlap visually; a route line connects sparse
observations and is not proof of the path travelled. Find My coordinates come
from nearby relay devices, not GPS measured by this beacon. Use Replay
for breadcrumbs: the collector does not invent speed or ignition telemetry, so
trip/stops analytics that depend on those fields have limitations.

## Operations

| Command | Purpose |
| --- | --- |
| `make tracking-status` | Service status and history/pending/rejected counts. |
| `make tracking-logs` | Collector and Traccar logs, without printing keys or coordinates. |
| `make tracking-down` | Stop only tracking services; preserve history and credentials. |
| `make tracking-up` | Start services, reconcile registration, and reload the key file. |
| `make tracking-backup` | Consistent SQLite snapshot and PostgreSQL dump. |
| `make tracking-replay` | Reconcile retained positions with Traccar again. |
| `make test-tracking` | Isolated real-Traccar tests with synthetic keys and disposable data. |

Stop tracking services before running the original `make down` if you also want
to stop the Apple endpoint. Never use `docker compose down -v` on the production
stack unless you deliberately intend to delete database volumes.

To stop collecting a particular tag, set its import-file `isActive` to `false`
and run `make tracking-up`. This does not delete its existing history. Disabling
the device in Traccar alone does not stop the separate Apple collector.

## Data and recovery

`.tracking/` is private, Git-ignored and excluded from image builds. It holds
credentials, configuration, Traccar assets and backups. Private beacon
keys stay in their original file and are mounted read-only only in the collector.
The collector runs as the host UID/GID to read that `0600` file. The canonical
database contains sensitive decrypted locations: protect it like a private key.

SQLite uses the project-scoped `tracking-history` Docker volume; PostgreSQL uses
`tracking-postgres`. SQLite must remain on Docker's native Linux storage: a
Docker Desktop host bind mount can break WAL coherence between the collector
and health/status processes. Keep `.tracking/` on a local filesystem, not NFS
or a cloud-sync folder. Back up the private devices JSON and the complete
`.tracking/` credentials/configuration alongside the database backups, off-device.
Do not copy a live SQLite file directly; use `make tracking-backup`.

Docker's collector health status checks process progress, not whether Apple has
provided a recent sighting. Check `latest_report`, `pending`, and `rejected` with
`make tracking-status` when investigating stale location data.

After restoring PostgreSQL or recreating Traccar, restore the matching credentials
and configuration, then use `make tracking-replay` to republish retained positions.
Do not delete `.tracking/` to fix a login problem: PostgreSQL retains its original
password and accounts. Restore the matching credentials from backup instead.

## Limits

This preserves reports received by the collector. It cannot recover reports
Apple never supplied or guarantee that polling catches everything before Apple's
undocumented limits apply. Initial collection requests the available seven-day
window, not a guaranteed seven-day archive. A powered, connected host is required.

Neither this project nor Traccar can turn crowd-sourced sightings into a gapless
GPS track. Key rotation is preserved as a privacy/protocol feature, not a way to
disable anti-stalking protections. Google Find Hub advertisements and credentials
are a separate protocol and are not added to this firmware.

Images are pinned to verified digests: Traccar 6.15.3 and PostgreSQL 17. The
collector has a hash-locked Python dependency set and no second Apple-login stack.
Remote access requires a separately secured tunnel or reverse proxy; do not
publish these HTTP ports directly to a public network.
