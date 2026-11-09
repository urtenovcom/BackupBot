"""Core backup execution engine orchestrating the complete backup lifecycle."""

import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backupbot.config import AppConfig, ProjectConfig
from backupbot.core.archiver import BackupArchiver
from backupbot.core.crypto import AgeEncryptor
from backupbot.core.dumper import DatabaseDumper, DumpError
from backupbot.core.hooks import HookExecutionError, run_hook
from backupbot.core.lock import BackupLock, LockAcquisitionError
from backupbot.core.retention import RetentionManager
from backupbot.db.state import StateDatabase
from backupbot.telegram.client import TelegramAPIError, TelegramClient
from backupbot.telegram.formatter import (
    build_filename,
    format_caption,
    format_failure_notification,
    format_success_summary,
)
from backupbot.utils.disk import check_disk_space, compute_sha256, format_size

logger = logging.getLogger("backupbot.runner")


class BackupRunner:
    """Orchestrates backup collection, archiving, encryption, splitting, and Telegram upload."""

    def __init__(self, config: AppConfig, telegram_client: Optional[TelegramClient] = None):
        self.config = config
        self.db = StateDatabase(config.storage.state_db)
        self.retention = RetentionManager(self.db)
        self.telegram = telegram_client or TelegramClient(
            bot_token=config.telegram.bot_token,
            message_thread_id=config.telegram.message_thread_id,
            api_url=config.telegram.api_url,
            timeout=config.telegram.timeout_seconds,
            max_retries=config.telegram.max_retries,
        )

    def run_all(self) -> Dict[str, bool]:
        """Run backups sequentially for all configured projects.

        Returns dict mapping project_id to success boolean.
        """
        results = {}
        logger.info("Starting sequential backup for all %d project(s)...", len(self.config.projects))
        for project in self.config.projects:
            success = self.run_project(project.id)
            results[project.id] = success
        return results

    def run_project(self, project_id: str) -> bool:
        """Execute complete backup flow for a single project with locking and error recovery."""
        project = next((p for p in self.config.projects if p.id == project_id), None)
        if not project:
            logger.error("Project with ID '%s' not found in configuration", project_id)
            return False

        # Acquire lock to prevent overlapping runs of this project
        lock_dir = os.path.join(self.config.storage.work_dir, "locks")
        lock_name = f"backup_{project.id}.lock"

        try:
            with BackupLock(lock_dir=lock_dir, name=lock_name, blocking=False):
                return self._execute_backup_flow(project)
        except LockAcquisitionError as e:
            logger.warning("Skipping backup for '%s': %s", project.id, e)
            return False

    def _execute_backup_flow(self, project: ProjectConfig) -> bool:
        """Internal execution flow for a project backup."""
        tz = ZoneInfo(project.timezone)
        started_at = datetime.now(tz)
        backup_id = f"{started_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        logger.info(
            "=== Starting backup for project '%s' (server: %s, backup_id: %s) ===",
            project.name,
            self.config.server_id,
            backup_id,
        )

        current_stage = "INIT"
        self.db.create_backup(
            backup_id=backup_id,
            project_id=project.id,
            server_id=self.config.server_id,
            started_at=started_at,
        )

        # Base directories
        project_work_dir = Path(self.config.storage.work_dir) / project.id / backup_id
        staging_dir = project_work_dir / "staging"
        dumps_dir = staging_dir / "dumps"
        files_dir = staging_dir / "files"
        volumes_dir = staging_dir / "volumes"
        archives_dir = project_work_dir / "archives"

        staging_dir.mkdir(parents=True, exist_ok=True)
        archives_dir.mkdir(parents=True, exist_ok=True)

        composition: List[Dict[str, Any]] = []

        try:
            # 1. Check disk space
            ok, free_mb = check_disk_space(self.config.storage.work_dir, self.config.storage.min_free_space_mb)
            if not ok:
                raise RuntimeError(
                    f"Insufficient free disk space in '{self.config.storage.work_dir}': "
                    f"{free_mb:.1f} MB available, minimum required {self.config.storage.min_free_space_mb} MB"
                )

            # 2. Pre-backup hook
            current_stage = "PRE_HOOK"
            self.db.update_backup(backup_id, stage=current_stage)
            if project.hooks.pre_backup:
                run_hook(project.hooks.pre_backup, "pre_backup")

            # 3. Database dumps
            current_stage = "DUMP"
            self.db.update_backup(backup_id, stage=current_stage)
            for db_cfg in project.databases:
                dump_path = DatabaseDumper.dump_database(db_cfg, str(dumps_dir))
                size = os.path.getsize(dump_path)
                composition.append(
                    {
                        "type": f"database_{db_cfg.type}",
                        "name": f"{db_cfg.container}:{db_cfg.db_name}",
                        "file": os.path.basename(dump_path),
                        "size_bytes": size,
                    }
                )

            # 4. Collect regular files & paths
            current_stage = "FILES"
            self.db.update_backup(backup_id, stage=current_stage)
            for p_path in project.paths:
                p = Path(p_path)
                if not p.exists():
                    logger.warning("Configured path '%s' does not exist, skipping", p_path)
                    continue

                dest = files_dir / p.name
                if p.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(p), str(dest))
                    composition.append({"type": "file", "name": str(p), "size_bytes": p.stat().st_size})
                elif p.is_dir():
                    shutil.copytree(
                        str(p),
                        str(dest),
                        symlinks=True,
                        ignore=shutil.ignore_patterns(*project.exclude) if project.exclude else None,
                    )
                    dir_size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
                    composition.append({"type": "directory", "name": str(p), "size_bytes": dir_size})

            # 5. Collect Docker volumes
            current_stage = "VOLUMES"
            self.db.update_backup(backup_id, stage=current_stage)
            for vol in project.volumes:
                vol_dest = volumes_dir / vol
                vol_size = self._backup_volume(vol, str(vol_dest), project.exclude)
                composition.append({"type": "docker_volume", "name": vol, "size_bytes": vol_size})

            # 6. Manifest
            finished_at = datetime.now(tz)
            manifest_path = BackupArchiver.write_manifest(
                staging_dir=str(staging_dir),
                backup_id=backup_id,
                server_id=self.config.server_id,
                project_id=project.id,
                project_name=project.name,
                started_at=started_at,
                finished_at=finished_at,
                timezone_str=project.timezone,
                composition=composition,
            )

            # 7. Create tar.gz
            current_stage = "ARCHIVE"
            self.db.update_backup(backup_id, stage=current_stage)
            raw_archive = archives_dir / f"{backup_id}.tar.gz"
            BackupArchiver.create_tar_gz(
                staging_dir=str(staging_dir),
                output_tar_gz=str(raw_archive),
                exclude_patterns=project.exclude,
            )

            # Staging directory can now be removed to conserve space
            shutil.rmtree(staging_dir, ignore_errors=True)

            # 8. Encrypt
            current_stage = "ENCRYPT"
            self.db.update_backup(backup_id, stage=current_stage)
            target_to_split: str
            encrypted = project.encryption.enabled

            if encrypted:
                encrypted_archive = archives_dir / f"{backup_id}.tar.gz.age"
                encryptor = AgeEncryptor(project.encryption.recipient)
                encryptor.encrypt_file(str(raw_archive), str(encrypted_archive))
                # Delete unencrypted archive
                if raw_archive.exists():
                    raw_archive.unlink()
                target_to_split = str(encrypted_archive)
            else:
                target_to_split = str(raw_archive)

            # 9. Splitting & SHA-256
            current_stage = "SPLIT"
            self.db.update_backup(backup_id, stage=current_stage)
            max_chunk_bytes = project.split_size_mb * 1024 * 1024
            base_filename = build_filename(
                server_id=self.config.server_id,
                project_id=project.id,
                started_at=started_at,
                backup_id=backup_id,
                encrypted=encrypted,
            )
            split_prefix = archives_dir / base_filename

            parts = BackupArchiver.split_file(
                input_file=target_to_split,
                output_prefix=str(split_prefix),
                max_size_bytes=max_chunk_bytes,
            )

            # If split created separate part files, remove the monolithic un-split file to save space
            if len(parts) > 1 and os.path.exists(target_to_split) and target_to_split != parts[0]["file_path"]:
                try:
                    os.remove(target_to_split)
                except OSError:
                    pass

            # Record parts in DB
            for p in parts:
                p["backup_id"] = backup_id
            self.db.record_parts(parts)

            total_size_bytes = sum(p["size_bytes"] for p in parts)
            self.db.update_backup(
                backup_id,
                total_parts=len(parts),
                total_size_bytes=total_size_bytes,
                archive_path=str(archives_dir),
            )

            # 10. Telegram Upload
            current_stage = "TELEGRAM_UPLOAD"
            self.db.update_backup(backup_id, stage=current_stage)
            self._upload_parts_to_telegram(project, backup_id, started_at, composition, total_size_bytes)

            # 11. Completion
            current_stage = "COMPLETED"
            finished_time = datetime.now(tz)
            self.db.update_backup(backup_id, status="SUCCESS", stage=current_stage, finished_at=finished_time)

            if self.config.telegram.notify_success:
                # Send final success confirmation message
                summary_msg = format_success_summary(
                    project_name=project.name,
                    server_id=self.config.server_id,
                    project_id=project.id,
                    started_at=started_at,
                    backup_id=backup_id,
                    total_parts=len(parts),
                    total_size_bytes=total_size_bytes,
                )
                try:
                    self.telegram.send_message(self.config.telegram.chat_id, summary_msg)
                except Exception as e:
                    logger.warning("Backup uploaded, but failed to send final confirmation message: %s", e)

            # 12. Local Retention Cleanup
            self.retention.cleanup_expired_backups(project.retention_days)

            logger.info("=== Backup %s for project '%s' COMPLETED SUCCESSFULLY ===", backup_id, project.name)
            return True

        except Exception as e:
            logger.error("Backup failed at stage %s: %s", current_stage, e, exc_info=True)
            self.db.update_backup(
                backup_id,
                status="FAILED",
                stage=current_stage,
                error_message=str(e),
            )
            # Send failure notification to Telegram
            self._notify_failure(project, backup_id, started_at, current_stage, str(e))
            return False

        finally:
            # Post-backup hook MUST always run even on errors!
            if project.hooks.post_backup:
                try:
                    run_hook(project.hooks.post_backup, "post_backup")
                except Exception as hook_err:
                    logger.error("Error executing post_backup hook: %s", hook_err)

    def _backup_volume(self, volume_name: str, dest_dir: str, exclude_patterns: List[str]) -> int:
        """Backup Docker volume data into dest_dir."""
        Path(dest_dir).mkdir(parents=True, exist_ok=True)

        # Check standard host path for Docker volume
        host_vol_path = Path("/var/lib/docker/volumes") / volume_name / "_data"
        if host_vol_path.is_dir():
            logger.info("Copying volume '%s' directly from %s...", volume_name, host_vol_path)
            shutil.copytree(
                str(host_vol_path),
                dest_dir,
                dirs_exist_ok=True,
                symlinks=True,
                ignore=shutil.ignore_patterns(*exclude_patterns) if exclude_patterns else None,
            )
            return sum(f.stat().st_size for f in Path(dest_dir).rglob("*") if f.is_file())

        # Check if helper docker CLI can stream volume via tar
        if shutil.which("docker"):
            try:
                logger.info("Extracting Docker volume '%s' via docker helper container...", volume_name)
                # Stream archive from volume via alpine container
                docker_cmd = [
                    "docker", "run", "--rm",
                    "-v", f"{volume_name}:/vol_data:ro",
                    "alpine", "tar", "-cf", "-", "-C", "/vol_data", ".",
                ]
                proc_docker = subprocess.Popen(docker_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                proc_tar = subprocess.Popen(["tar", "-xf", "-", "-C", dest_dir], stdin=proc_docker.stdout)
                proc_docker.stdout.close()
                proc_tar.communicate()
                proc_docker.communicate()

                if proc_tar.returncode == 0 and proc_docker.returncode == 0:
                    return sum(f.stat().st_size for f in Path(dest_dir).rglob("*") if f.is_file())
            except Exception as e:
                logger.warning("Could not backup volume '%s' via Docker CLI: %s", volume_name, e)

        # If custom directory mounted directly
        custom_mount = Path("/volumes") / volume_name
        if custom_mount.is_dir():
            shutil.copytree(
                str(custom_mount),
                dest_dir,
                dirs_exist_ok=True,
                symlinks=True,
                ignore=shutil.ignore_patterns(*exclude_patterns) if exclude_patterns else None,
            )
            return sum(f.stat().st_size for f in Path(dest_dir).rglob("*") if f.is_file())

        logger.warning(
            "Volume '%s' could not be found directly or via Docker container. Backing up empty volume marker.",
            volume_name,
        )
        marker_file = Path(dest_dir) / ".volume_not_found"
        marker_file.write_text(f"Docker volume '{volume_name}' was not accessible during backup.")
        return 0

    def _upload_parts_to_telegram(
        self,
        project: ProjectConfig,
        backup_id: str,
        started_at: datetime,
        composition: List[Dict[str, Any]],
        total_size_bytes: int,
    ) -> None:
        """Upload all pending/unconfirmed parts to Telegram."""
        # Build concise composition summary
        comp_summary = ", ".join(
            item.get("file") or item.get("name", item["type"]) for item in composition
        ) or "Files & Data"

        all_parts = self.db.get_parts(backup_id)
        total_parts = len(all_parts)

        unconfirmed = self.db.get_unconfirmed_parts(backup_id)
        logger.info(
            "Uploading %d/%d part(s) to Telegram chat %s...",
            len(unconfirmed),
            total_parts,
            self.config.telegram.chat_id,
        )

        for part in unconfirmed:
            part_idx = part["part_index"]
            file_path = part["file_path"]
            filename = part["filename"]
            sha256 = part["sha256"]
            size_bytes = part["size_bytes"]

            caption = format_caption(
                project_name=project.name,
                server_id=self.config.server_id,
                project_id=project.id,
                started_at=started_at,
                composition_summary=comp_summary,
                size_bytes=total_size_bytes,
                backup_id=backup_id,
                part_index=part_idx,
                total_parts=total_parts,
                sha256=sha256,
            )

            msg_id = self.telegram.send_document(
                chat_id=self.config.telegram.chat_id,
                file_path=file_path,
                filename=filename,
                caption=caption,
            )

            # Record success in SQLite immediately after delivery
            self.db.mark_part_uploaded(backup_id, part_idx, msg_id)

    def _notify_failure(
        self,
        project: ProjectConfig,
        backup_id: str,
        started_at: datetime,
        stage: str,
        error_message: str,
    ) -> None:
        """Send error alert message to Telegram."""
        all_parts = self.db.get_parts(backup_id)
        total_parts = len(all_parts)
        delivered_parts = sum(1 for p in all_parts if p.get("status") == "UPLOADED")

        alert_text = format_failure_notification(
            project_name=project.name,
            server_id=self.config.server_id,
            project_id=project.id,
            started_at=started_at,
            stage=stage,
            backup_id=backup_id,
            delivered_parts=delivered_parts,
            total_parts=total_parts,
            error_message=error_message,
        )

        try:
            self.telegram.send_message(self.config.telegram.chat_id, alert_text)
        except Exception as e:
            logger.error("Failed to deliver error notification to Telegram: %s", e)
