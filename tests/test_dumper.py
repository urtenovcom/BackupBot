"""Tests for database dump command generation and execution handling."""

from unittest.mock import MagicMock, patch
import pytest

from backupbot.config import DatabaseConfig
from backupbot.core.dumper import DatabaseDumper, DumpError


def test_dump_postgres_command_generation(tmp_path):
    db_cfg = DatabaseConfig(
        type="postgres",
        container="my_pg_container",
        db_name="prod_db",
        user="db_user",
        password="secret_password",
        extra_args=["--clean"],
    )

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        out_path = DatabaseDumper.dump_database(db_cfg, str(tmp_path))

        assert mock_popen.called
        cmd = mock_popen.call_args[0][0]
        assert cmd[:3] == ["docker", "exec", "-i"]
        assert "-e" in cmd
        assert "PGPASSWORD=secret_password" in cmd
        assert "my_pg_container" in cmd
        assert "pg_dump" in cmd
        assert "-U" in cmd and "db_user" in cmd
        assert "-d" in cmd and "prod_db" in cmd
        assert "--clean" in cmd


def test_dump_postgres_all_databases(tmp_path):
    db_cfg = DatabaseConfig(
        type="postgres",
        container="my_pg_container",
        db_name="all",
        user="postgres",
    )

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        DatabaseDumper.dump_database(db_cfg, str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert "pg_dumpall" in cmd
        assert "-U" in cmd and "postgres" in cmd


def test_dump_mysql_command_generation(tmp_path):
    db_cfg = DatabaseConfig(
        type="mysql",
        container="my_mysql_container",
        db_name="app_db",
        user="root",
        password="root_password",
        extra_args=["--single-transaction"],
    )

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        DatabaseDumper.dump_database(db_cfg, str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert cmd[:3] == ["docker", "exec", "-i"]
        assert "-e" in cmd
        assert "MYSQL_PWD=root_password" in cmd
        assert "mysqldump" in cmd
        assert "-u" in cmd and "root" in cmd
        assert "app_db" in cmd
        assert "--single-transaction" in cmd


def test_dump_failure_raises_error(tmp_path):
    db_cfg = DatabaseConfig(
        type="postgres",
        container="failing_container",
        db_name="prod_db",
    )

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"database not found error")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        with pytest.raises(DumpError) as exc:
            DatabaseDumper.dump_database(db_cfg, str(tmp_path))

        assert "database not found error" in str(exc.value)
