"""Command-line interface for BackupBot."""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from backupbot.config import load_config
from backupbot.core.runner import BackupRunner
from backupbot.db.state import StateDatabase
from backupbot.scheduler.runner import Scheduler
from backupbot.utils.disk import format_size
from backupbot.utils.logging import setup_logging


def get_default_config_path() -> str:
    """Find config file from environment or default locations."""
    env_path = os.environ.get("BACKUPBOT_CONFIG")
    if env_path and os.path.isfile(env_path):
        return env_path
    for p in ["config.yaml", "config.yml", "/etc/backupbot/config.yaml"]:
        if os.path.isfile(p):
            return p
    return "config.yaml"


def cmd_validate_config(args: argparse.Namespace) -> int:
    """Validate YAML configuration file."""
    try:
        cfg = load_config(args.config)
        print(f"✅ Configuration '{args.config}' is valid!")
        print(f"Server ID: {cfg.server_id}")
        print(f"Configured projects ({len(cfg.projects)}):")
        for p in cfg.projects:
            enc_status = f"age ({p.encryption.recipient[:15]}...)" if p.encryption.enabled else "disabled"
            sched = p.schedule or "manual only"
            print(f"  - [{p.id}] {p.name} | Schedule: {sched} ({p.timezone}) | Encryption: {enc_status} | Retention: {p.retention_days}d")
        return 0
    except Exception as e:
        print(f"❌ Configuration error in '{args.config}': {e}", file=sys.stderr)
        return 1


def cmd_list_projects(args: argparse.Namespace) -> int:
    """List all configured projects."""
    try:
        cfg = load_config(args.config)
        print(f"Projects configured on server '{cfg.server_id}':\n")
        header = f"{'ID':<20} {'NAME':<25} {'SCHEDULE':<15} {'TIMEZONE':<18} {'RETENTION':<10}"
        print(header)
        print("-" * len(header))
        for p in cfg.projects:
            sched = p.schedule or "-"
            print(f"{p.id:<20} {p.name:<25} {sched:<15} {p.timezone:<18} {p.retention_days} days")
        return 0
    except Exception as e:
        print(f"❌ Failed to list projects: {e}", file=sys.stderr)
        return 1


def cmd_backup(args: argparse.Namespace) -> int:
    """Run backup for a specific project or all projects."""
    logger = setup_logging(verbose=args.verbose)
    try:
        cfg = load_config(args.config)
        runner = BackupRunner(cfg)

        if args.all:
            results = runner.run_all()
            all_ok = all(results.values())
            print("\nBackup results:")
            for pid, ok in results.items():
                status_icon = "✅" if ok else "❌"
                print(f"  {status_icon} {pid}")
            return 0 if all_ok else 1
        elif args.project:
            ok = runner.run_project(args.project)
            if ok:
                print(f"✅ Backup for project '{args.project}' completed successfully!")
                return 0
            else:
                print(f"❌ Backup for project '{args.project}' failed!", file=sys.stderr)
                return 1
        else:
            print("❌ Must specify either --project <id> or --all", file=sys.stderr)
            return 1
    except Exception as e:
        logger.error("Error executing backup: %s", e, exc_info=args.verbose)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Show recent backups status from SQLite database."""
    try:
        cfg = load_config(args.config)
        db = StateDatabase(cfg.storage.state_db)
        backups = db.list_backups(limit=args.limit)

        if not backups:
            print(f"No backup history found in {cfg.storage.state_db}")
            return 0

        print(f"Recent backup runs (server: {cfg.server_id}):\n")
        header = f"{'BACKUP ID':<30} {'PROJECT':<16} {'STATUS':<10} {'STAGE':<12} {'STARTED AT':<20} {'SIZE':<10} {'PARTS'}"
        print(header)
        print("-" * len(header))

        for b in backups:
            size_str = format_size(b.get("total_size_bytes") or 0)
            parts_str = f"{b.get('total_parts', 0)}"
            started = b.get("started_at", "")[:19].replace("T", " ")
            status = b.get("status", "")
            stage = b.get("stage", "") or "-"
            print(
                f"{b['backup_id']:<30} {b['project_id']:<16} {status:<10} {stage:<12} {started:<20} {size_str:<10} {parts_str}"
            )
            if b.get("error_message"):
                print(f"   ↳ Error: {b['error_message']}")

        return 0
    except Exception as e:
        print(f"❌ Failed to query status: {e}", file=sys.stderr)
        return 1


def cmd_run_scheduler(args: argparse.Namespace) -> int:
    """Run continuous scheduler daemon."""
    setup_logging(verbose=args.verbose)
    try:
        cfg = load_config(args.config)
        scheduler = Scheduler(cfg)
        scheduler.start()
        return 0
    except Exception as e:
        print(f"❌ Scheduler crashed: {e}", file=sys.stderr)
        return 1


def main() -> None:
    """CLI entrypoint."""
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "-c", "--config",
        default=get_default_config_path(),
        help="Path to YAML configuration file (default: config.yaml or BACKUPBOT_CONFIG)",
    )
    common_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    parser = argparse.ArgumentParser(
        prog="backupbot",
        description="BackupBot: Automated Docker project backups to Telegram",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate-config
    subparsers.add_parser(
        "validate-config",
        parents=[common_parser],
        help="Validate YAML configuration syntax and requirements",
    )

    # list-projects
    subparsers.add_parser(
        "list-projects",
        parents=[common_parser],
        help="List all configured projects and schedules",
    )

    # backup
    backup_parser = subparsers.add_parser(
        "backup",
        parents=[common_parser],
        help="Run backup immediately",
    )
    backup_group = backup_parser.add_mutually_exclusive_group(required=True)
    backup_group.add_argument("-p", "--project", help="ID of the project to backup")
    backup_group.add_argument("-a", "--all", action="store_true", help="Backup all configured projects sequentially")

    # status
    status_parser = subparsers.add_parser(
        "status",
        parents=[common_parser],
        help="Show backup history and status",
    )
    status_parser.add_argument("-n", "--limit", type=int, default=15, help="Number of records to show")

    # run-scheduler
    subparsers.add_parser(
        "run-scheduler",
        parents=[common_parser],
        help="Run the automated background scheduler loop",
    )

    args = parser.parse_args()

    handlers = {
        "validate-config": cmd_validate_config,
        "list-projects": cmd_list_projects,
        "backup": cmd_backup,
        "status": cmd_status,
        "run-scheduler": cmd_run_scheduler,
    }

    exit_code = handlers[args.command](args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
