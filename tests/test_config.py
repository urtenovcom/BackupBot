"""Tests for configuration parsing, env variable expansion, and validations."""

import os
import pytest
from pydantic import ValidationError

from backupbot.config import AppConfig, expand_env_vars, load_config


def test_expand_env_vars(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "my_value")
    assert expand_env_vars("Hello ${TEST_VAR}!") == "Hello my_value!"
    assert expand_env_vars("${UNDEFINED_VAR:-default_val}") == "default_val"
    assert expand_env_vars("Plain text") == "Plain text"


def test_valid_config(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123456789:ABCDEF1234567890abcdef1234567890")
    monkeypatch.setenv("CHAT_ID", "-100123456789")

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
server_id: "vps_test_01"
telegram:
  bot_token: "${BOT_TOKEN}"
  chat_id: "${CHAT_ID}"
storage:
  work_dir: "/tmp/backupbot_test"
  state_db: "/tmp/backupbot_test/state.db"
projects:
  - id: "my_site"
    name: "My Site"
    schedule: "0 4 * * *"
    timezone: "Europe/Moscow"
    paths:
      - "/tmp/test_dir"
    encryption:
      enabled: true
      recipient: "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"
    retention_days: 7
    split_size_mb: 45
"""
    )

    cfg = load_config(str(cfg_file))
    assert cfg.server_id == "vps_test_01"
    assert cfg.telegram.bot_token == "123456789:ABCDEF1234567890abcdef1234567890"
    assert cfg.telegram.chat_id == "-100123456789"
    assert len(cfg.projects) == 1
    assert cfg.projects[0].id == "my_site"
    assert cfg.projects[0].retention_days == 7


def test_invalid_server_id():
    with pytest.raises(ValidationError) as exc:
        AppConfig.model_validate(
            {
                "server_id": "vps-01!",  # Invalid symbols
                "telegram": {"bot_token": "123:abc", "chat_id": "123"},
                "projects": [
                    {"id": "p1", "name": "P1", "encryption": {"enabled": False}}
                ],
            }
        )
    assert "server_id" in str(exc.value)


def test_invalid_project_id():
    with pytest.raises(ValidationError) as exc:
        AppConfig.model_validate(
            {
                "server_id": "vps_01",
                "telegram": {"bot_token": "123:abc", "chat_id": "123"},
                "projects": [
                    {"id": "project with spaces", "name": "P1", "encryption": {"enabled": False}}
                ],
            }
        )
    assert "Project id" in str(exc.value)


def test_duplicate_project_id():
    with pytest.raises(ValidationError) as exc:
        AppConfig.model_validate(
            {
                "server_id": "vps_01",
                "telegram": {"bot_token": "123:abc", "chat_id": "123"},
                "projects": [
                    {"id": "proj_1", "name": "P1", "encryption": {"enabled": False}},
                    {"id": "proj_1", "name": "P2", "encryption": {"enabled": False}},
                ],
            }
        )
    assert "Duplicate project id 'proj_1'" in str(exc.value)


def test_invalid_timezone():
    with pytest.raises(ValidationError) as exc:
        AppConfig.model_validate(
            {
                "server_id": "vps_01",
                "telegram": {"bot_token": "123:abc", "chat_id": "123"},
                "projects": [
                    {
                        "id": "proj_1",
                        "name": "P1",
                        "timezone": "Mars/Olympus",
                        "encryption": {"enabled": False},
                    }
                ],
            }
        )
    assert "Unknown timezone" in str(exc.value)


def test_invalid_age_recipient():
    with pytest.raises(ValidationError) as exc:
        AppConfig.model_validate(
            {
                "server_id": "vps_01",
                "telegram": {"bot_token": "123:abc", "chat_id": "123"},
                "projects": [
                    {
                        "id": "proj_1",
                        "name": "P1",
                        "encryption": {
                            "enabled": True,
                            "recipient": "not_an_age_key",
                        },
                    }
                ],
            }
        )
    assert "Invalid age recipient public key" in str(exc.value)
