"""Tests for Telegram caption, hashtag, and filename formatting."""

from datetime import datetime
from zoneinfo import ZoneInfo

from backupbot.telegram.formatter import (
    MAX_CAPTION_LENGTH,
    build_filename,
    format_caption,
    format_failure_notification,
    format_hashtags,
    format_success_summary,
)


def test_build_filename_single_part():
    dt = datetime(2026, 11, 7, 3, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    fn = build_filename("vps_01", "my_website", dt, "bk_1234", total_parts=1, encrypted=True)
    assert fn == "vps_01__my_website__2026-11-07_03-00-00__bk_1234.tar.gz.age"


def test_build_filename_multi_part():
    dt = datetime(2026, 11, 7, 3, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    fn1 = build_filename("vps_01", "my_website", dt, "bk_1234", part_index=1, total_parts=3, encrypted=True)
    fn2 = build_filename("vps_01", "my_website", dt, "bk_1234", part_index=2, total_parts=3, encrypted=True)
    assert fn1 == "vps_01__my_website__2026-11-07_03-00-00__bk_1234.tar.gz.age.part01"
    assert fn2 == "vps_01__my_website__2026-11-07_03-00-00__bk_1234.tar.gz.age.part02"


def test_build_filename_unencrypted():
    dt = datetime(2026, 11, 7, 3, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    fn = build_filename("vps_01", "my_website", dt, "bk_1234", encrypted=False)
    assert fn == "vps_01__my_website__2026-11-07_03-00-00__bk_1234.tar.gz"


def test_format_hashtags():
    dt = datetime(2026, 11, 7, 3, 0, 0)
    tags = format_hashtags("vps_01", "my_website", dt, is_error=False)
    assert tags == "#backup #project_my_website #server_vps_01 #date_2026_11_07"

    err_tags = format_hashtags("vps_01", "my_website", dt, is_error=True)
    assert err_tags == "#backup_error #project_my_website #server_vps_01 #date_2026_11_07"


def test_format_caption_within_limit():
    dt = datetime(2026, 11, 7, 3, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    caption = format_caption(
        project_name="Корпоративный Сайт",
        server_id="vps_01",
        project_id="my_website",
        started_at=dt,
        composition_summary="PostgreSQL, uploads, compose",
        size_bytes=155189248,
        backup_id="20261107_030000_abc123",
        part_index=1,
        total_parts=1,
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    assert len(caption) <= MAX_CAPTION_LENGTH
    assert "📦 Резервная копия" in caption
    assert "Проект: Корпоративный Сайт" in caption
    assert "Сервер: vps_01" in caption
    assert "Часть: 1/1" in caption
    assert "148.0 MB" in caption
    assert "#backup #project_my_website #server_vps_01 #date_2026_11_07" in caption


def test_format_caption_truncates_long_composition():
    dt = datetime(2026, 11, 7, 3, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    huge_composition = "x" * 2000
    caption = format_caption(
        project_name="Big Project",
        server_id="vps_01",
        project_id="big_project",
        started_at=dt,
        composition_summary=huge_composition,
        size_bytes=1000,
        backup_id="bk_id",
        part_index=1,
        total_parts=1,
        sha256="abc",
    )
    assert len(caption) <= MAX_CAPTION_LENGTH
    assert "..." in caption


def test_format_success_summary():
    dt = datetime(2026, 11, 7, 3, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    summary = format_success_summary(
        project_name="My Website",
        server_id="vps_01",
        project_id="my_website",
        started_at=dt,
        backup_id="bk_999",
        total_parts=3,
        total_size_bytes=145000000,
    )
    assert "✅ Резервная копия успешно отправлена" in summary
    assert "Частей отправлено: 3/3" in summary
    assert "#project_my_website" in summary


def test_format_failure_notification():
    dt = datetime(2026, 11, 7, 3, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    alert = format_failure_notification(
        project_name="My Website",
        server_id="vps_01",
        project_id="my_website",
        started_at=dt,
        stage="DUMP",
        backup_id="bk_999",
        delivered_parts=1,
        total_parts=3,
        error_message="pg_dump: connection to database failed",
    )
    assert "❌ Ошибка резервного копирования" in alert
    assert "Этап: DUMP" in alert
    assert "Доставлено частей: 1/3" in alert
    assert "pg_dump: connection to database failed" in alert
    assert "#backup_error" in alert
