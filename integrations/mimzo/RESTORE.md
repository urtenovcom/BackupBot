# Mimzo recovery

Archives contain secrets. Decrypt only on a trusted machine. The age identity is kept on the owner's computer under ~/.ssh/mimzo-backup/identity.txt; it is never stored on the VPS or sent to Telegram.

1. Download all parts of the SAME backup ID/server/project. Compare each SHA256 with the Telegram captions. Concatenate numbered parts in numeric order if split; a single .age file needs no concatenation.
2. Decrypt with `age -d -i identity.txt -o backup.tar.gz backup.age` (or BackupBot AgeEncryptor.decrypt_file). Inspect tar listing before extracting in an empty private directory; do not extract over a live server.
3. Read manifest.json. The database dump is under dumps/; files/export contains deployment files, running container inspections (with environment), TLS files and this guide.
4. Reconstruct exact compose/env/image versions from deployment/compose.json or remnawave/docker-compose.yml and containers.json. For panel, preserve APP_SECRET, database state, user keys/shortUUID and API secrets. Never rotate them during recovery.
5. PostgreSQL plain SQL: create an EMPTY compatible PostgreSQL instance/role/database, then `psql -v ON_ERROR_STOP=1 -U ROLE -d DATABASE < dump.sql`. Restore data before starting the bot/panel. Never restore against live production DB. Check users, subscriptions, wallet/transactions and schema migration version. PostgreSQL18 used on Nov9.
6. Production: bot-runtime.tar.gz contains /app code/dependency metadata from the running bot; cabinet-static.tar.gz contains the actual current HTML/JS, landing-runtime.tar.gz contains the running landing. Rebuild images if their local-only tags aren't available; original source/lock/build files should be preserved in these snapshots. containers.json records exact previous environment/entrypoints/mounts. Restore uploads/data and deployment files to the original paths.
7. Panel: restore /opt/remnawave, /opt/mimzo-geo, rw-balancer, checker, /etc/letsencrypt. Restore database then start panel/subpage/front. Keep mimzo.ru/sub.mimzo.ru paths and routing/update headers unchanged. Verify one existing subscription for Happ and INCY.
8. CDN193: quota/budget.sqlite was created with the SQLite backup API and integrity-checked. Restore it with gateway stopped, restore gateway config/code and service. Do not reset per-user budgets or start a second writer on another server. Restore remnanode and Telegram relay config and certificates.
9. Check actual VPN traffic, email login, payment callback idempotency and tariff fulfillment before DNS/bot polling cutover. Run exactly one production Telegram polling process.

Each server is a separate snapshot. Cross-server PostgreSQL dumps are not an atomic distributed snapshot. Redis caches/sessions and historical archives are intentionally excluded. Backup does not cancel/replace the existing production stack.
