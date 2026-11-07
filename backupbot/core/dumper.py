"""Database dumping via standard container CLI tools."""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List

from backupbot.config import DatabaseConfig

logger = logging.getLogger("backupbot.dumper")


class DumpError(Exception):
    """Raised when database dump operation fails."""
    pass


class DatabaseDumper:
    """Manages dumping PostgreSQL and MySQL/MariaDB databases from Docker containers."""

    @classmethod
    def dump_database(cls, db_cfg: DatabaseConfig, output_dir: str) -> str:
        """Execute database dump and save to output_dir.

        Returns path to the generated dump file.
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        db_type = db_cfg.type.lower()
        safe_db_name = db_cfg.db_name.replace("/", "_")
        dump_filename = f"{db_type}__{db_cfg.container}__{safe_db_name}.sql"
        output_path = os.path.join(output_dir, dump_filename)

        logger.info(
            "Creating %s dump for container '%s', database '%s'...",
            db_type.upper(),
            db_cfg.container,
            db_cfg.db_name,
        )

        if db_type == "postgres":
            cls._dump_postgres(db_cfg, output_path)
        elif db_type in ("mysql", "mariadb"):
            cls._dump_mysql(db_cfg, output_path)
        else:
            raise DumpError(f"Unsupported database type: {db_type}")

        dump_size = os.path.getsize(output_path)
        logger.info("Successfully dumped database to %s (%d bytes)", dump_filename, dump_size)
        return output_path

    @classmethod
    def _dump_postgres(cls, db_cfg: DatabaseConfig, output_file: str) -> None:
        cmd = ["docker", "exec", "-i"]
        if db_cfg.password:
            cmd.extend(["-e", f"PGPASSWORD={db_cfg.password}"])

        cmd.append(db_cfg.container)

        if db_cfg.db_name.lower() in ("all", "--all-databases"):
            cmd.extend(["pg_dumpall", "-U", db_cfg.user])
        else:
            cmd.extend(["pg_dump", "-U", db_cfg.user, "-d", db_cfg.db_name])

        if db_cfg.extra_args:
            cmd.extend(db_cfg.extra_args)

        cls._run_dump_stream(cmd, output_file, db_cfg.container)

    @classmethod
    def _dump_mysql(cls, db_cfg: DatabaseConfig, output_file: str) -> None:
        cmd = ["docker", "exec", "-i"]
        if db_cfg.password:
            cmd.extend(["-e", f"MYSQL_PWD={db_cfg.password}"])

        cmd.append(db_cfg.container)
        cmd.extend(["mysqldump", "-u", db_cfg.user])

        if db_cfg.db_name.lower() in ("all", "--all-databases"):
            cmd.append("--all-databases")
        else:
            cmd.append(db_cfg.db_name)

        if db_cfg.extra_args:
            cmd.extend(db_cfg.extra_args)

        cls._run_dump_stream(cmd, output_file, db_cfg.container)

    @classmethod
    def _run_dump_stream(cls, cmd: List[str], output_file: str, container_name: str) -> None:
        """Run dump command streaming stdout to file and capturing stderr."""
        with open(output_file, "wb") as out_f:
            process = subprocess.Popen(
                cmd,
                stdout=out_f,
                stderr=subprocess.PIPE,
            )
            _, stderr = process.communicate()

        if process.returncode != 0:
            # Cleanup broken output file
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                except OSError:
                    pass

            err_text = stderr.decode("utf-8", errors="replace").strip() if stderr else "Unknown error"
            raise DumpError(
                f"Failed to dump database from container '{container_name}' (exit code {process.returncode}): {err_text}"
            )
