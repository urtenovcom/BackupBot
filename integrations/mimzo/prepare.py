#!/usr/bin/env python3
"""Collect current Mimzo runtime files; never stop or alter production services."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit
import yaml

os.umask(0o077)
ROOT = Path('/var/lib/backupbot/export')


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def copy_required(source, name):
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f'Required backup source missing: {source}')
    dest = ROOT / name
    if source.is_dir():
        shutil.copytree(source, dest, symlinks=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)


def container_tar(container, path, name):
    # tar output is trusted local container state, stored as an archive (not extracted).
    with (ROOT / name).open('wb') as out:
        command(['docker', 'exec', container, 'tar', '-czf', '-',
                 '--exclude=./.venv', '--exclude=./venv', '--exclude=./node_modules',
                 '--exclude=./.git', '--exclude=./logs', '--exclude=./data',
                 '--exclude=./uploads', '--exclude=__pycache__',
                 '-C', path, '.'], stdout=out)


def validate_live_database(inspection, config_path):
    env = dict(v.split('=', 1) for v in inspection['Config']['Env'] if '=' in v)
    live_db = urlsplit(env['DATABASE_URL']).path.lstrip('/')
    configured_db = yaml.safe_load(config_path.read_text())['projects'][0]['databases'][0]['db_name']
    if live_db != configured_db:
        raise RuntimeError('Backup database does not match live bot DATABASE_URL')


def main(role):
    roles = {
        'production': ['mimzo-recovery-api-1', 'mimzo-recovery-ui-1',
                       'mimzo-recovery-db-1', 'mimzo-recovery-redis-1',
                       'mimzo-recovery-preview-edge-1', 'mimzo-recovery-landing-1'],
        'panel': ['remnawave', 'remnawave-db', 'remnawave-nginx',
                  'remnawave-subscription-page', 'remnawave-redis'],
        'cdn': ['remnanode', 'mimzo-telegram-relay', 'caddy'],
    }
    names = roles[role]
    inspections = json.loads(subprocess.check_output(['docker', 'inspect', *names]))
    for item in inspections:
        if not item['State']['Running']:
            raise RuntimeError(f'Required container is stopped: {item["Name"]}')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in ROOT.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()
    (ROOT / 'containers.json').write_text(json.dumps(inspections, indent=2))
    (ROOT / 'RESTORE.md').write_text(Path('/opt/backupbot/integrations/mimzo/RESTORE.md').read_text())
    copy_required('/etc/letsencrypt', 'letsencrypt')
    copy_required('/etc/cron.d', 'cron.d')
    copy_required('/etc/systemd/system', 'systemd')
    if role == 'production':
        validate_live_database(inspections[0], Path('/etc/backupbot/config.yaml'))
        base = Path('/opt/mimzo-recovery')
        # Copy root-level deployment files, not historic release/backup folders.
        target = ROOT / 'deployment'
        target.mkdir()
        for path in base.iterdir():
            if path.is_file() and (path.name == '.env' or path.suffix in {'.json', '.env', '.conf', '.inc', '.py', '.sh'}):
                shutil.copy2(path, target / path.name)
        for name in ['.env', 'production.env', 'compose.json', 'preview_api.py']:
            if not (target / name).is_file():
                raise FileNotFoundError(f'Missing deployment file: {name}')
        for name in ['preview-tls', 'public-geo-preview']:
            copy_required(base / name, name)
        copy_required(base / 'bot-uploads', 'bot-uploads')
        shutil.copytree(base / 'bot-data', ROOT / 'bot-data', symlinks=True,
                        ignore=shutil.ignore_patterns('backups', '__pycache__', '*.log'))
        container_tar('mimzo-recovery-api-1', '/app', 'bot-runtime.tar.gz')
        container_tar('mimzo-recovery-ui-1', '/usr/share/nginx/html', 'cabinet-static.tar.gz')
        container_tar('mimzo-recovery-landing-1', '/app', 'landing-runtime.tar.gz')
        with (ROOT / 'bot-pip-freeze.txt').open('wb') as out:
            command(['docker', 'exec', 'mimzo-recovery-api-1', 'python', '-c', "import importlib.metadata; print(*sorted(d.metadata['Name']+'=='+d.version for d in importlib.metadata.distributions()), sep=chr(10))"], stdout=out)
    elif role == 'panel':
        for source, name in [('/opt/remnawave', 'remnawave'), ('/opt/mimzo-geo', 'mimzo-geo'),
                             ('/opt/rw-balancer', 'rw-balancer'), ('/opt/xray-checker', 'xray-checker'),
                             ('/root/apitok.txt', 'panel-api-token.txt')]:
            copy_required(source, name)
    else:
        for source, name in [('/opt/mimzo-cdn-quota/gateway.py', 'quota/gateway.py'),
                             ('/opt/mimzo-cdn-quota/gateway-config.json', 'quota/gateway-config.json'),
                             ('/opt/mimzo-telegram-relay', 'telegram-relay'),
                             ('/opt/remnanode', 'remnanode'),
                             ('/opt/remnawave/caddy', 'caddy'),
                             ('/var/lib/docker/volumes/caddy-ssl-data/_data', 'caddy-data')]:
            copy_required(source, name)
        source = sqlite3.connect('file:/opt/mimzo-cdn-quota/budget.sqlite?mode=ro', uri=True)
        with sqlite3.connect(str(ROOT / 'quota/budget.sqlite')) as dest:
            source.backup(dest)
            assert dest.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        source.close()
    print(f'Collected {role} runtime into {ROOT}', flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
