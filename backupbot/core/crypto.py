"""Age encryption and decryption management."""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

try:
    import pyrage
    from pyrage import x25519
    HAS_PYRAGE = True
except ImportError:
    HAS_PYRAGE = False

logger = logging.getLogger("backupbot.crypto")


class CryptoError(Exception):
    """Exception raised on encryption/decryption failure."""
    pass


class AgeEncryptor:
    """Handles age encryption and decryption streaming."""

    def __init__(self, recipient_public_key: Optional[str] = None):
        self.recipient_key = recipient_public_key.strip() if recipient_public_key else None

    def encrypt_file(self, input_file: str, output_file: str) -> None:
        """Encrypt input_file to output_file using recipient public key."""
        if not self.recipient_key:
            raise CryptoError("Recipient public key not set for encryption")

        if not os.path.isfile(input_file):
            raise FileNotFoundError(f"Input file not found for encryption: {input_file}")

        Path(output_file).parent.mkdir(parents=True, exist_ok=True)

        # 1. Try pyrage (pure-Rust Python binding)
        if HAS_PYRAGE:
            try:
                recipient = x25519.Recipient.from_str(self.recipient_key)
                pyrage.encrypt_file(input_file, output_file, [recipient])
                logger.debug("Successfully encrypted %s -> %s using pyrage", input_file, output_file)
                return
            except Exception as e:
                logger.warning("pyrage encryption failed, checking CLI age fallback: %s", e)

        # 2. Fallback to CLI age tool if installed
        age_bin = shutil.which("age")
        if age_bin:
            cmd = [age_bin, "-r", self.recipient_key, "-o", output_file, input_file]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise CryptoError(f"age CLI encryption failed (code {result.returncode}): {result.stderr.strip()}")
            logger.debug("Successfully encrypted %s -> %s using age CLI", input_file, output_file)
            return

        raise CryptoError(
            "No age encryption backend available. Install pyrage ('pip install pyrage') or system age binary ('apt install age')."
        )

    @classmethod
    def decrypt_file(cls, input_file: str, output_file: str, identity_key_or_file: str) -> None:
        """Decrypt input_file to output_file using age private identity key or key file."""
        if not os.path.isfile(input_file):
            raise FileNotFoundError(f"Input file not found: {input_file}")

        key_str = identity_key_or_file.strip()
        key_file_path: Optional[str] = None

        if os.path.isfile(key_str):
            key_file_path = key_str
            with open(key_str, "r", encoding="utf-8") as f:
                content = f.read().strip()
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("AGE-SECRET-KEY-1"):
                        key_str = line
                        break

        # 1. Try pyrage
        if HAS_PYRAGE:
            try:
                identity = x25519.Identity.from_str(key_str)
                pyrage.decrypt_file(input_file, output_file, [identity])
                logger.debug("Successfully decrypted %s -> %s using pyrage", input_file, output_file)
                return
            except Exception as e:
                logger.warning("pyrage decryption failed, checking CLI age fallback: %s", e)

        # 2. Fallback to CLI age tool
        age_bin = shutil.which("age")
        if age_bin:
            temp_key_file = False
            if not key_file_path:
                temp_key_path = f"/tmp/age_ident_{os.getpid()}.key"
                with open(temp_key_path, "w", encoding="utf-8") as f:
                    f.write(key_str + "\n")
                key_file_path = temp_key_path
                temp_key_file = True

            try:
                cmd = [age_bin, "-d", "-i", key_file_path, "-o", output_file, input_file]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise CryptoError(f"age CLI decryption failed (code {result.returncode}): {result.stderr.strip()}")
                logger.debug("Successfully decrypted %s -> %s using age CLI", input_file, output_file)
                return
            finally:
                if temp_key_file and key_file_path and os.path.exists(key_file_path):
                    os.remove(key_file_path)

        raise CryptoError(
            "No age decryption backend available. Install pyrage ('pip install pyrage') or system age binary ('apt install age')."
        )
