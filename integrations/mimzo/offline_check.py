"""Offline full-pipeline verification: never contacts Telegram, uses separate state."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, '/opt/backupbot')
from backupbot.config import load_config
from backupbot.core.runner import BackupRunner
from backupbot.utils.disk import compute_sha256

os.umask(0o077)
os.environ['TELEGRAM_BOT_TOKEN'] = 'offline:NOT_A_REAL_TOKEN'
os.environ['TELEGRAM_CHAT_ID'] = 'offline-NO_DELIVERY'
os.environ['TELEGRAM_MESSAGE_THREAD_ID'] = '1'
for line in Path('/etc/backupbot/public.env').read_text().splitlines():
    k, v = line.split('=', 1)
    os.environ[k] = v
config = load_config('/etc/backupbot/config.yaml')
config.storage.state_db = '/var/lib/backupbot/offline-state.db'
config.storage.work_dir = '/var/lib/backupbot/offline-work'


class OfflineSink:
    def __init__(self):
        self.parts = []

    def send_document(self, **kwargs):
        p = Path(kwargs['file_path'])
        self.parts.append({'file': str(p), 'sha256': compute_sha256(str(p)), 'bytes': p.stat().st_size})
        return len(self.parts)

    def send_message(self, *args, **kwargs):
        return 1


sink = OfflineSink()
result = BackupRunner(config, telegram_client=sink).run_all()
assert all(result.values()), 'Offline backup failed'
Path('/var/lib/backupbot/offline-result.json').write_text(json.dumps({'mode': 'OFFLINE_NOT_SENT', 'projects': result, 'parts': sink.parts}, indent=2))
print(json.dumps({'mode': 'OFFLINE_NOT_SENT', 'projects': result, 'parts': len(sink.parts), 'bytes': sum(x['bytes'] for x in sink.parts)}))
