# Mimzo deployment

Hosts: production141.133.180.149; panel177.3.208.71; CDN193.23.202.9.
Native venv /opt/backupbot/.venv; runtime /var/lib/backupbot; private config /etc/backupbot. Service mimzo-backupbot.service enabled on all3 hosts Nov9 after real delivery verification.

Schedules Europe/Moscow DAILY: production03:00, panel03:00, CDN03:00. Retention7days encrypted, parts45MiB. Separate success summaries disabled (notify_success=false); files/captions and failure alerts still sent to topic Mimzo.

Set AGE_PUBLIC_KEY in public.env. Dedicated TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID/TELEGRAM_MESSAGE_THREAD_ID go in telegram.env (root0600). Source both env files when invoking CLI manually; systemd loads them automatically. Never write real tokens into this repository.

Offline test: from /opt/backupbot run .venv/bin/python integrations/mimzo/offline_check.py. It uses separate offline-state.db/work and a local sink; no Telegram calls. Its SUCCESS records prove packaging only, not delivery.

Activation after recipient verification: source env files (set -a), run python -m backupbot.cli backup --all --config /etc/backupbot/config.yaml, verify all Telegram file message IDs, then systemctl enable --now mimzo-backupbot. Check status and health of original apps.

Private age identity stays only at ~/.ssh/mimzo-backup/identity.txt on owner's computer. Preserve another offline copy separately. Actual backup archive restore steps in RESTORE.md.

Verified Nov9: actual production DB is bot_upgrade, NOT empty default recovery. Collector rejects config/live DB mismatch. PostgreSQL18 restored into disposable network-none containers: bot486 users/468 subscriptions/631 transactions; panel415 users/10nodes/11hosts. Containers removed afterward. CDN SQLite integrity ok. Encrypted archives fetched to owner's machine and decrypted. Offline verification does not prove Telegram delivery.

Telegram target: Alazar Backups group -1004373207327, topic Mimzo message_thread_id2. First real document message IDs: production10,panel6,CDN8; all state.db parts UPLOADED. Initial delivery Nov9~17:08Moscow. Next scheduled production18:00,panel18:20,CDN18:40. Notifications and documents use same topic.

Nov9 owner changed frequency to daily and requested quiet success. Next jobs Nov10 03:00/03:20/03:40Moscow. No extra test archives sent for this configuration change.

Owner synchronized all3 daily jobs to03:00Europe/Moscow Nov9. Archives arrive independently as each completes; quiet success retained.

Release notifications: only177 runs mimzo-release-watch.timer at00:10/06:10/12:10/18:10Europe/Moscow. Source backupbot/release_watch.py; /etc/backupbot/releases.json; state /var/lib/backupbot/release-watch/state.json. Dedicated private target owner362867621 (verified /start); never uses backup group/topic. Tracks remnawave/backend,node and BEDOLAGA bot,cabinet stable GitHub releases. First observation establishes baseline, future newer stable versions notify once; failed delivery leaves previous tag for retry; per-repository state atomically saved. No updates installed. Current initial upstream baselines3.4.8/3.4.4/5.2.0/1.82.0 are upstream releases, not an assertion of installed versions on all servers. This checker does not alert on unreleased commits. API errors logged and private alert at most once daily.
