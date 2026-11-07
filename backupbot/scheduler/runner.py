"""Background scheduler for automated backups based on cron expressions and timezones."""

import logging
import signal
import time
from datetime import datetime
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from croniter import croniter

from backupbot.config import AppConfig, ProjectConfig
from backupbot.core.runner import BackupRunner

logger = logging.getLogger("backupbot.scheduler")


class Scheduler:
    """Manages scheduled execution of project backups."""

    def __init__(self, config: AppConfig, runner: Optional[BackupRunner] = None):
        self.config = config
        self.runner = runner or BackupRunner(config)
        self.running = False
        self._next_runs: Dict[str, float] = {}

    def _setup_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown on SIGTERM and SIGINT."""
        def handle_stop(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info("Received signal %s. Initiating graceful shutdown...", sig_name)
            self.running = False

        signal.signal(signal.SIGTERM, handle_stop)
        signal.signal(signal.SIGINT, handle_stop)

    def _compute_next_run(self, project: ProjectConfig, now_epoch: float) -> Optional[float]:
        """Compute epoch timestamp of the next scheduled run using croniter and project timezone."""
        if not project.schedule or not project.schedule.strip():
            return None

        tz = ZoneInfo(project.timezone)
        current_dt = datetime.fromtimestamp(now_epoch, tz=tz)

        try:
            it = croniter(project.schedule.strip(), current_dt)
            next_dt = it.get_next(datetime)
            return next_dt.timestamp()
        except Exception as e:
            logger.error(
                "Invalid schedule expression '%s' for project '%s': %s",
                project.schedule,
                project.id,
                e,
            )
            return None

    def start(self) -> None:
        """Start the scheduler loop."""
        self._setup_signal_handlers()
        self.running = True

        scheduled_projects = [p for p in self.config.projects if p.schedule]
        if not scheduled_projects:
            logger.warning("No projects have a configured schedule. Scheduler will remain idle.")

        now = time.time()
        for p in scheduled_projects:
            next_ts = self._compute_next_run(p, now)
            if next_ts:
                self._next_runs[p.id] = next_ts
                tz = ZoneInfo(p.timezone)
                next_str = datetime.fromtimestamp(next_ts, tz=tz).strftime("%Y-%m-%d %H:%M:%S %Z")
                logger.info("Project '%s' scheduled: next run at %s (cron: '%s')", p.id, next_str, p.schedule)

        logger.info("Scheduler started. Waiting for jobs... (Press Ctrl+C to stop)")

        while self.running:
            now = time.time()

            for p in scheduled_projects:
                if not self.running:
                    break

                next_ts = self._next_runs.get(p.id)
                if next_ts is not None and now >= next_ts:
                    logger.info("Triggering scheduled backup for project '%s'...", p.id)
                    try:
                        self.runner.run_project(p.id)
                    except Exception as e:
                        logger.error("Error executing scheduled backup for '%s': %s", p.id, e, exc_info=True)

                    # Compute subsequent run
                    new_next = self._compute_next_run(p, time.time())
                    if new_next:
                        self._next_runs[p.id] = new_next
                        tz = ZoneInfo(p.timezone)
                        next_str = datetime.fromtimestamp(new_next, tz=tz).strftime("%Y-%m-%d %H:%M:%S %Z")
                        logger.info("Next run for project '%s' scheduled at %s", p.id, next_str)

            # Sleep in short increments to respond promptly to SIGTERM/SIGINT
            sleep_chunks = 20
            for _ in range(sleep_chunks):
                if not self.running:
                    break
                time.sleep(0.5)

        logger.info("Scheduler stopped cleanly.")
