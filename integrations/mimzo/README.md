# Mimzo deployment

Hosts: production141.133.180.149; panel177.3.208.71; CDN193.23.202.9.
Native venv /opt/backupbot/.venv; runtime /var/lib/backupbot; private config /etc/backupbot. Service mimzo-backupbot.service is installed but disabled until Telegram credentials arrive.

Schedules Europe/Moscow every6h: production00:00/06:00/12:00/18:00; panel20minutes later; CDN40minutes later. Retention7days encrypted, parts45MiB.

Set AGE_PUBLIC_KEY in public.env. Dedicated TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID go in telegram.env (root0600). Source both env files when invoking CLI manually; systemd loads them automatically. Never write real tokens into this repository.

Offline test: from /opt/backupbot run .venv/bin/python integrations/mimzo/offline_check.py. It uses separate offline-state.db/work and a local sink; no Telegram calls. Its SUCCESS records prove packaging only, not delivery.

Activation after recipient verification: source env files (set -a), run python -m backupbot.cli backup --all --config /etc/backupbot/config.yaml, verify all Telegram file message IDs, then systemctl enable --now mimzo-backupbot. Check status and health of original apps.

Private age identity stays only at ~/.ssh/mimzo-backup/identity.txt on owner's computer. Preserve another offline copy separately. Actual backup archive restore steps in RESTORE.md.

Verified Nov9: actual production DB is bot_upgrade, NOT empty default recovery. Collector rejects config/live DB mismatch. PostgreSQL18 restored into disposable network-none containers: bot486 users/468 subscriptions/631 transactions; panel415 users/10nodes/11hosts. Containers removed afterward. CDN SQLite integrity ok. Encrypted archives fetched to owner's machine and decrypted. Offline verification does not prove Telegram delivery.
