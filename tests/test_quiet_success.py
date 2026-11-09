from unittest.mock import MagicMock
import pytest
from backupbot.config import AppConfig
from backupbot.core.runner import BackupRunner


@pytest.mark.parametrize('fails', [False, True])
def test_quiet_success_keeps_failure_alerts(tmp_path, fails):
    source = tmp_path / 'file.txt'
    source.write_text('backup data')
    cfg = AppConfig.model_validate({
        'server_id': 'test',
        'telegram': {'bot_token': '123:TEST', 'chat_id': '1', 'notify_success': False},
        'storage': {'state_db': str(tmp_path / 'state.db'), 'work_dir': str(tmp_path / 'work'), 'min_free_space_mb': 10},
        'projects': [{'id': 'test', 'name': 'test', 'paths': [str(source)], 'encryption': {'enabled': False}}],
    })
    client = MagicMock()
    client.send_document.return_value = 1
    if fails:
        client.send_document.side_effect = RuntimeError('upload failed')
    assert BackupRunner(cfg, telegram_client=client).run_project('test') is not fails
    assert client.send_document.call_count == 1
    assert client.send_message.call_count == int(fails)
