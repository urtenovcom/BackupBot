"""Tests for CLI commands: validate-config, list-projects, backup, status."""

import sys
from unittest.mock import MagicMock, patch

from backupbot.cli import cmd_backup, cmd_list_projects, cmd_status, cmd_validate_config


def test_cli_validate_config(tmp_path):
    cfg_file = tmp_path / "valid.yaml"
    cfg_file.write_text(
        """
server_id: "srv_1"
telegram:
  bot_token: "123:abc1234567890abcdef12345"
  chat_id: "12345"
projects:
  - id: "p1"
    name: "Project One"
    encryption:
      enabled: false
"""
    )
    args = MagicMock()
    args.config = str(cfg_file)
    exit_code = cmd_validate_config(args)
    assert exit_code == 0


def test_cli_validate_config_invalid(tmp_path):
    bad_cfg = tmp_path / "invalid.yaml"
    bad_cfg.write_text("invalid: [yaml")
    args = MagicMock()
    args.config = str(bad_cfg)
    exit_code = cmd_validate_config(args)
    assert exit_code == 1


def test_cli_list_projects(tmp_path):
    cfg_file = tmp_path / "valid.yaml"
    cfg_file.write_text(
        """
server_id: "srv_1"
telegram:
  bot_token: "123:abc1234567890abcdef12345"
  chat_id: "12345"
projects:
  - id: "app"
    name: "Web Application"
    encryption:
      enabled: false
"""
    )
    args = MagicMock()
    args.config = str(cfg_file)
    exit_code = cmd_list_projects(args)
    assert exit_code == 0


def test_cli_backup_single_project(tmp_path):
    cfg_file = tmp_path / "valid.yaml"
    cfg_file.write_text(
        """
server_id: "srv_1"
telegram:
  bot_token: "123:abc1234567890abcdef12345"
  chat_id: "12345"
projects:
  - id: "app"
    name: "Web Application"
    encryption:
      enabled: false
"""
    )
    args = MagicMock()
    args.config = str(cfg_file)
    args.verbose = False
    args.project = "app"
    args.all = False

    with patch("backupbot.cli.BackupRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner.run_project.return_value = True
        mock_runner_cls.return_value = mock_runner

        exit_code = cmd_backup(args)
        assert exit_code == 0
        mock_runner.run_project.assert_called_once_with("app")


def test_cli_status(tmp_path):
    db_file = tmp_path / "state.db"
    cfg_file = tmp_path / "valid.yaml"
    cfg_file.write_text(
        f"""
server_id: "srv_1"
telegram:
  bot_token: "123:abc1234567890abcdef12345"
  chat_id: "12345"
storage:
  state_db: "{db_file}"
projects:
  - id: "app"
    name: "Web Application"
    encryption:
      enabled: false
"""
    )
    args = MagicMock()
    args.config = str(cfg_file)
    args.limit = 10
    exit_code = cmd_status(args)
    assert exit_code == 0
