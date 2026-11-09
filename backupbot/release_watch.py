"""Notify owner about new stable upstream releases; never install anything."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone

import requests

from backupbot.telegram.client import TelegramClient
from backupbot.utils.logging import register_secret, setup_logging


def version(tag):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', tag)
    if not match:
        raise ValueError('Unexpected stable release version format')
    return tuple(map(int, match.groups()))


def check_releases(items, state, fetch, notify):
    for item in items:
        repo = item['repo']
        release = fetch(repo)
        if release.get('draft') or release.get('prerelease'):
            continue
        tag = release['tag_name']
        current = version(tag)
        old = state.get(repo)
        if old:
            if current <= version(old['tag']):
                continue
            # Release text is reference data, sent as plain text without parse_mode.
            message = (f"Доступен новый стабильный релиз: {item['name']} {tag}\n"
                       f"Предыдущий отслеживаемый релиз: {old['tag']}\n"
                       f"{release['html_url']}\n\n"
                       "Автоматическая установка отключена. Перед обновлением нужна проверка совместимости Mimzo.")
            notify(message)
        state[repo] = {'tag': tag, 'url': release['html_url'],
                       'observed_at': datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/backupbot/releases.json')
    args = parser.parse_args()
    os.umask(0o077)
    logger = setup_logging()
    cfg = json.loads(Path(args.config).read_text())
    path = Path(cfg['state_path'])
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    token = os.environ['TELEGRAM_BOT_TOKEN']
    register_secret(token)
    # Dedicated private target: never uses the archive group or its topic ID.
    client = TelegramClient(token, max_retries=3, timeout=30)
    session = requests.Session()
    session.headers.update({'Accept': 'application/vnd.github+json',
                            'User-Agent': 'Mimzo-Release-Watch',
                            'X-GitHub-Api-Version': '2022-11-28'})

    def fetch(repo):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('Invalid GitHub repository')
        response = session.get('https://api.github.com/repos/'+repo+'/releases/latest', timeout=20)
        response.raise_for_status()
        return response.json()

    def save(state):
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        temp.replace(path)

    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(path.read_text()) if path.exists() else {}
        try:
            for item in cfg['repositories']:
                check_releases([item], state, fetch,
                               lambda text: client.send_message(cfg['private_chat_id'], text))
                save(state)  # Persist each successful notification independently.
            logger.info('Stable releases checked: %d repositories', len(cfg['repositories']))
        except Exception as exc:
            logger.error('Release check failed: %s', type(exc).__name__)
            today = datetime.now(timezone.utc).date().isoformat()
            if state.get('_error_day') != today:
                try:
                    client.send_message(cfg['private_chat_id'], 'Mimzo: проверка обновлений временно не завершилась. Повторю при следующем запуске. Резервные копии работают отдельно.')
                    state['_error_day'] = today
                    save(state)
                except Exception:
                    pass
            raise SystemExit(1)


if __name__ == '__main__':
    main()
