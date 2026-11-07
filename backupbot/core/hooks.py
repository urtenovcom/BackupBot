"""Execution of pre-backup and post-backup lifecycle hooks."""

import logging
import subprocess
from typing import Optional

logger = logging.getLogger("backupbot.hooks")


class HookExecutionError(Exception):
    """Raised when a pre-backup or post-backup command fails."""
    pass


def run_hook(command: Optional[str], hook_type: str, timeout: int = 300) -> None:
    """Run shell hook command.

    Args:
        command: Shell command to run
        hook_type: 'pre_backup' or 'post_backup'
        timeout: Execution timeout in seconds
    """
    if not command or not command.strip():
        return

    cmd = command.strip()
    logger.info("Running %s hook...", hook_type)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            error_msg = f"{hook_type} hook failed with code {result.returncode}: {result.stderr.strip()}"
            logger.error(error_msg)
            raise HookExecutionError(error_msg)
        logger.info("%s hook completed successfully", hook_type)
    except subprocess.TimeoutExpired as e:
        error_msg = f"{hook_type} hook timed out after {timeout} seconds"
        logger.error(error_msg)
        raise HookExecutionError(error_msg) from e
    except Exception as e:
        if not isinstance(e, HookExecutionError):
            logger.error("Error executing %s hook: %s", hook_type, e)
            raise HookExecutionError(f"{hook_type} hook execution error: {e}") from e
        raise
