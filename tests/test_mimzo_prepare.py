import pytest
from integrations.mimzo.prepare import validate_live_database


def test_live_bot_database_matches_backup(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('projects:\n- databases:\n  - db_name: bot_upgrade\n')
    validate_live_database({'Config': {'Env': ['DATABASE_URL=postgresql://user:secret@db/bot_upgrade']}}, path)


def test_empty_default_database_is_rejected(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('projects:\n- databases:\n  - db_name: recovery\n')
    with pytest.raises(RuntimeError, match='does not match'):
        validate_live_database({'Config': {'Env': ['DATABASE_URL=postgresql://user:secret@db/bot_upgrade']}}, path)
