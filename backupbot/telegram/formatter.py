"""Caption, filename, and message formatting for Telegram."""

from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from backupbot.utils.disk import format_size

MAX_CAPTION_LENGTH = 1024


def build_filename(
    server_id: str,
    project_id: str,
    started_at: datetime,
    backup_id: str,
    part_index: Optional[int] = None,
    total_parts: Optional[int] = None,
    encrypted: bool = True,
) -> str:
    """Generate standardized filename:

    vps_01__my_website__2026-11-07_03-00-00__<backup_id>.tar.gz.age[.part01]
    """
    date_str = started_at.strftime("%Y-%m-%d_%H-%M-%S")
    ext = ".tar.gz.age" if encrypted else ".tar.gz"

    base_name = f"{server_id}__{project_id}__{date_str}__{backup_id}{ext}"
    if total_parts is not None and total_parts > 1 and part_index is not None:
        return f"{base_name}.part{part_index:02d}"
    return base_name


def format_hashtags(server_id: str, project_id: str, started_at: datetime, is_error: bool = False) -> str:
    """Generate search hashtags based on server_id, project_id, and date."""
    base_tag = "#backup_error" if is_error else "#backup"
    date_tag = f"#date_{started_at.strftime('%Y_%m_%d')}"
    return f"{base_tag} #project_{project_id} #server_{server_id} {date_tag}"


def format_caption(
    project_name: str,
    server_id: str,
    project_id: str,
    started_at: datetime,
    composition_summary: str,
    size_bytes: int,
    backup_id: str,
    part_index: int,
    total_parts: int,
    sha256: str,
) -> str:
    """Format single part caption complying with the 1024 characters Telegram limit."""
    # Format date with timezone abbreviation or offset
    date_str = started_at.strftime("%d.%m.%Y %H:%M:%S %Z").strip()
    hashtags = format_hashtags(server_id, project_id, started_at, is_error=False)
    size_str = format_size(size_bytes)
    part_str = f"{part_index}/{total_parts}"

    header = "📦 Резервная копия\n"
    lines = [
        f"Проект: {project_name}",
        f"Сервер: {server_id}",
        f"Дата: {date_str}",
        f"Состав: {composition_summary}",
        f"Размер: {size_str}",
        f"Backup ID: {backup_id}",
        f"Часть: {part_str}",
        f"SHA-256: {sha256}",
    ]
    body = "\n".join(lines)
    full_caption = f"{header}{body}\n\n{hashtags}"

    # If exceeding 1024 chars, truncate composition summary gracefully
    if len(full_caption) > MAX_CAPTION_LENGTH:
        overflow = len(full_caption) - MAX_CAPTION_LENGTH + 5
        truncated_comp = (
            composition_summary[:-overflow] + "..." if len(composition_summary) > overflow else "..."
        )
        lines[3] = f"Состав: {truncated_comp}"
        body = "\n".join(lines)
        full_caption = f"{header}{body}\n\n{hashtags}"

    return full_caption[:MAX_CAPTION_LENGTH]


def format_success_summary(
    project_name: str,
    server_id: str,
    project_id: str,
    started_at: datetime,
    backup_id: str,
    total_parts: int,
    total_size_bytes: int,
) -> str:
    """Format final confirmation message sent after all parts have been delivered."""
    date_str = started_at.strftime("%d.%m.%Y %H:%M:%S %Z").strip()
    hashtags = format_hashtags(server_id, project_id, started_at, is_error=False)
    size_str = format_size(total_size_bytes)

    lines = [
        "✅ Резервная копия успешно отправлена",
        f"Проект: {project_name}",
        f"Сервер: {server_id}",
        f"Дата: {date_str}",
        f"Backup ID: {backup_id}",
        f"Частей отправлено: {total_parts}/{total_parts}",
        f"Общий размер: {size_str}",
        "",
        hashtags,
    ]
    return "\n".join(lines)


def format_failure_notification(
    project_name: str,
    server_id: str,
    project_id: str,
    started_at: datetime,
    stage: str,
    backup_id: str,
    delivered_parts: int,
    total_parts: int,
    error_message: str,
) -> str:
    """Format failure alert message with failure stage and delivery status."""
    date_str = started_at.strftime("%d.%m.%Y %H:%M:%S %Z").strip()
    hashtags = format_hashtags(server_id, project_id, started_at, is_error=True)

    delivered_str = f"{delivered_parts}/{total_parts}" if total_parts > 0 else "0"

    # Truncate very long error messages so message fits well within Telegram limits (4096 chars)
    safe_error = error_message.strip()
    if len(safe_error) > 1500:
        safe_error = safe_error[:1500] + "... (truncated)"

    lines = [
        "❌ Ошибка резервного копирования",
        f"Проект: {project_name}",
        f"Сервер: {server_id}",
        f"Дата: {date_str}",
        f"Этап: {stage}",
        f"Backup ID: {backup_id}",
        f"Доставлено частей: {delivered_str}",
        f"Ошибка: {safe_error}",
        "",
        hashtags,
    ]
    return "\n".join(lines)
