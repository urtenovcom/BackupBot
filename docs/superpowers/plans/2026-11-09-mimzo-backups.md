# Mimzo BackupBot deployment plan

Goal: encrypted, restorable Telegram backups of production141, panel177 and CDN193.
Architecture: existing BackupBot on each host in a private Python venv; host-native Docker CLI; no additional public ports. The user is preparing a dedicated token/chat. Until supplied, only offline verification runs, no enabled sender.

- [x] Inventory live mounts, DB names and runtime sources; exclude raw PostgreSQL volumes, historical dumps, logs and caches.
- [x] Add integration configs, a fail-fast pre-backup collector, disabled systemd service and restore instructions. Every6h at separate minutes, Europe/Moscow; encrypted retention7days;45MiB parts.
- [x] Generate age identity exclusively on owner's computer; public recipient only on VPS.
- [x] Deploy files and isolated venv without restarting production containers.
- [x] Produce offline encrypted archives, copy offsite, decrypt, verify manifests, restore SQL into disposable isolated containers and check schema/data. Offline state must be separate from real Telegram delivery state.
- [x] Once token/chat arrive: verify recipient, send first real archives, verify message IDs, then enable schedule. Never label simulated uploads as real delivery.

Risks/constraints: independently timed PostgreSQL snapshots across hosts, not distributed transaction. Quota SQLite uses SQLite backup API. Runtime code/assets copied from active containers, not stale source checkouts. Preserve APP_SECRET, API tokens and TLS/config in encrypted archive; no credentials in Git. Do not send age private identity to VPS or Telegram. No production restore or service stop.
