"""Configuration models, loading, and validation."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from backupbot.utils.logging import register_secret

ID_REGEX = re.compile(r"^[a-zA-Z0-9_]+$")
ENV_VAR_REGEX = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")


def expand_env_vars(text: str) -> str:
    """Expand ${VAR_NAME} or ${VAR_NAME:-default} from environment variables."""
    if not isinstance(text, str):
        return text

    def replace_match(match: re.Match) -> str:
        var_name = match.group(1)
        default_val = match.group(2) if match.group(2) is not None else ""
        return os.environ.get(var_name, default_val)

    return ENV_VAR_REGEX.sub(replace_match, text)


def deep_expand_env(data: Any) -> Any:
    """Recursively expand environment variables in dicts, lists, and strings."""
    if isinstance(data, dict):
        return {k: deep_expand_env(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [deep_expand_env(i) for i in data]
    elif isinstance(data, str):
        return expand_env_vars(data)
    return data


class TelegramConfig(BaseModel):
    notify_success: bool = Field(default=True, description="Send separate success summary after upload")
    message_thread_id: Optional[int] = Field(default=None, ge=1, description="Telegram forum topic ID")
    bot_token: str = Field(..., description="Telegram Bot API Token")
    chat_id: str = Field(..., description="Telegram Chat or Channel ID (e.g. -100...)")
    api_url: str = Field(default="https://api.telegram.org", description="Telegram Bot API base URL")
    timeout_seconds: int = Field(default=120, ge=5, description="Timeout for Telegram API requests in seconds")
    max_retries: int = Field(default=5, ge=1, description="Max retries for Telegram API requests")

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Telegram bot_token cannot be empty")
        # Format check for typical bot tokens: digits:alphanumeric_or_symbols
        if ":" not in v:
            raise ValueError("Telegram bot_token seems invalid, must contain ':'")
        register_secret(v)
        return v

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, v: Any) -> str:
        s = str(v).strip()
        if not s:
            raise ValueError("Telegram chat_id cannot be empty")
        return s


class DatabaseConfig(BaseModel):
    type: str = Field(..., description="Database type: postgres, mysql, mariadb")
    container: str = Field(..., description="Docker container name or ID")
    db_name: str = Field(..., description="Database name to dump, or 'all'")
    user: str = Field(default="postgres", description="Database user")
    password: Optional[str] = Field(default=None, description="Database password")
    extra_args: List[str] = Field(default_factory=list, description="Additional CLI args for dump tool")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("postgres", "postgresql", "mysql", "mariadb"):
            raise ValueError(f"Unsupported database type '{v}'. Supported: postgres, mysql, mariadb")
        return "postgres" if v == "postgresql" else v

    @field_validator("password")
    @classmethod
    def register_db_password(cls, v: Optional[str]) -> Optional[str]:
        if v:
            register_secret(v)
        return v


class HooksConfig(BaseModel):
    pre_backup: Optional[str] = Field(default=None, description="Shell command before backup begins")
    post_backup: Optional[str] = Field(default=None, description="Shell command after backup finishes (runs always)")


class EncryptionConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether age encryption is enabled")
    recipient: Optional[str] = Field(default=None, description="Age public recipient key (age1...)")

    @model_validator(mode="after")
    def validate_encryption(self) -> "EncryptionConfig":
        if self.enabled:
            if not self.recipient:
                raise ValueError("Encryption is enabled, but recipient age public key is not provided")
            rec = self.recipient.strip()
            if not (rec.startswith("age1") and len(rec) >= 50):
                raise ValueError(f"Invalid age recipient public key: '{rec}'. Must start with age1...")
            self.recipient = rec
        return self


class ProjectConfig(BaseModel):
    id: str = Field(..., description="Unique stable project ID (letters, numbers, underscores)")
    name: str = Field(..., description="Display name of the project")
    schedule: Optional[str] = Field(default=None, description="Cron expression (e.g. '0 3 * * *')")
    timezone: str = Field(default="Europe/Moscow", description="Timezone name")
    paths: List[str] = Field(default_factory=list, description="Files and directories to backup")
    volumes: List[str] = Field(default_factory=list, description="Docker volumes to backup")
    databases: List[DatabaseConfig] = Field(default_factory=list, description="Databases to dump")
    exclude: List[str] = Field(default_factory=list, description="Exclusion patterns (glob/tar)")
    hooks: HooksConfig = Field(default_factory=HooksConfig, description="Pre and post backup hooks")
    encryption: EncryptionConfig = Field(default_factory=EncryptionConfig, description="Encryption settings")
    retention_days: int = Field(default=7, ge=0, description="Local backup retention period in days (0 = delete immediately after send)")
    split_size_mb: int = Field(default=45, ge=1, le=2000, description="Split archive into parts of max size in MB")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        v = v.strip()
        if not ID_REGEX.match(v):
            raise ValueError(f"Project id '{v}' must contain only latin letters, digits, and underscores")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError:
            raise ValueError(f"Unknown timezone '{v}'")
        return v


class StorageConfig(BaseModel):
    work_dir: str = Field(default="/tmp/backupbot", description="Temporary working directory for dumps and archives")
    state_db: str = Field(default="/var/lib/backupbot/state.db", description="Path to SQLite state database")
    min_free_space_mb: float = Field(default=500.0, ge=10.0, description="Minimum free disk space required in MB")


class AppConfig(BaseModel):
    server_id: str = Field(..., description="Unique stable server identifier (letters, digits, underscores)")
    telegram: TelegramConfig = Field(..., description="Telegram settings")
    storage: StorageConfig = Field(default_factory=StorageConfig, description="Storage and state database settings")
    projects: List[ProjectConfig] = Field(..., min_length=1, description="List of configured projects")

    @field_validator("server_id")
    @classmethod
    def validate_server_id(cls, v: str) -> str:
        v = v.strip()
        if not ID_REGEX.match(v):
            raise ValueError(f"server_id '{v}' must contain only latin letters, digits, and underscores")
        return v

    @model_validator(mode="after")
    def validate_unique_project_ids(self) -> "AppConfig":
        seen_ids = set()
        for p in self.projects:
            if p.id in seen_ids:
                raise ValueError(f"Duplicate project id '{p.id}' found in configuration")
            seen_ids.add(p.id)
        return self


def load_config(config_path: str) -> AppConfig:
    """Load, expand environment variables, and validate YAML configuration."""
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    if not isinstance(raw_data, dict):
        raise ValueError(f"Configuration file {config_path} is empty or not a valid YAML dictionary")

    expanded_data = deep_expand_env(raw_data)
    return AppConfig.model_validate(expanded_data)
