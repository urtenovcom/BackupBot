"""Telegram Bot API client with retries, 429 handling, and streaming uploads."""

import logging
import os
import time
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("backupbot.telegram")


class TelegramAPIError(Exception):
    """Exception raised when Telegram API returns an error or fails repeatedly."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class TelegramClient:
    """Client for Telegram Bot API supporting streaming uploads, retries, and rate-limit backoff."""

    def __init__(
        self,
        bot_token: str,
        api_url: str = "https://api.telegram.org",
        timeout: int = 120,
        max_retries: int = 5,
        session: Optional[requests.Session] = None,
        message_thread_id: Optional[int] = None,
    ):
        self.message_thread_id = message_thread_id
        self.bot_token = bot_token.strip()
        self.base_url = f"{api_url.rstrip('/')}/bot{self.bot_token}"
        self.timeout = timeout
        self.max_retries = max_retries

        if session is not None:
            self.session = session
        else:
            self.session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=Retry(
                    total=3,
                    backoff_factor=1,
                    status_forcelist=[500, 502, 503, 504],
                    allowed_methods=["GET", "POST"],
                ),
            )
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute HTTP request with exponential backoff and 429 rate limit adherence."""
        url = f"{self.base_url}/{endpoint}"
        attempt = 0
        backoff = 2.0

        while attempt < self.max_retries:
            attempt += 1
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    data=data,
                    files=files,
                    timeout=self.timeout,
                )

                # Check for rate limiting 429
                if response.status_code == 429:
                    try:
                        resp_json = response.json()
                        retry_after = resp_json.get("parameters", {}).get("retry_after", backoff)
                    except Exception:
                        retry_after = backoff

                    logger.warning(
                        "Telegram rate limit reached (HTTP 429). Sleeping for %.1f seconds before retry %d/%d",
                        retry_after,
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(float(retry_after) + 0.5)
                    continue

                if response.status_code >= 500:
                    logger.warning(
                        "Telegram server error (HTTP %d). Retry %d/%d in %.1fs",
                        response.status_code,
                        attempt,
                        self.max_retries,
                        backoff,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                resp_json = response.json()
                if not response.ok or not resp_json.get("ok"):
                    desc = resp_json.get("description", response.text)
                    error_code = resp_json.get("error_code", response.status_code)
                    raise TelegramAPIError(
                        f"Telegram API error {error_code}: {desc}",
                        status_code=error_code,
                        response_data=resp_json,
                    )

                return resp_json

            except (requests.ConnectionError, requests.Timeout) as e:
                logger.warning(
                    "Network error communicating with Telegram (%s). Retry %d/%d in %.1fs",
                    type(e).__name__,
                    attempt,
                    self.max_retries,
                    backoff,
                )
                if attempt >= self.max_retries:
                    raise TelegramAPIError(f"Network error after {self.max_retries} attempts: {e}") from e
                time.sleep(backoff)
                backoff *= 2

        raise TelegramAPIError(f"Failed to execute Telegram request after {self.max_retries} attempts")

    def send_message(self, chat_id: str, text: str) -> int:
        """Send a plain text message to the specified chat. Returns message_id."""
        logger.debug("Sending message to chat %s (length %d chars)", chat_id, len(text))
        result = self._request_with_retry(
            method="POST",
            endpoint="sendMessage",
            data={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
                **({"message_thread_id": self.message_thread_id} if self.message_thread_id is not None else {}),
            },
        )
        return result["result"]["message_id"]

    def send_document(
        self,
        chat_id: str,
        file_path: str,
        filename: str,
        caption: str,
    ) -> int:
        """Stream a document file to Telegram chat. Returns message_id."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Backup file not found for upload: {file_path}")

        file_size = os.path.getsize(file_path)
        logger.info(
            "Uploading document '%s' (%d bytes) to Telegram chat %s...",
            filename,
            file_size,
            chat_id,
        )

        with open(file_path, "rb") as file_stream:
            files = {
                "document": (filename, file_stream, "application/octet-stream"),
            }
            data = {
                "chat_id": chat_id,
                "caption": caption,
                **({"message_thread_id": self.message_thread_id} if self.message_thread_id is not None else {}),
            }
            result = self._request_with_retry(
                method="POST",
                endpoint="sendDocument",
                data=data,
                files=files,
            )

        message_id = result["result"]["message_id"]
        logger.info("Successfully delivered '%s' (message_id=%s)", filename, message_id)
        return message_id
