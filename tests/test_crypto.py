"""Tests for age encryption and decryption."""

import pyrage
import pytest

from backupbot.core.crypto import AgeEncryptor, CryptoError


def test_age_encryption_and_decryption_flow(tmp_path):
    # Generate test age identity
    identity = pyrage.x25519.Identity.generate()
    recipient_pub = str(identity.to_public())
    secret_key = str(identity)

    # Prepare sample plaintext file
    plaintext_file = tmp_path / "data.txt"
    plaintext_data = b"Secret database dump and configuration content" * 100
    plaintext_file.write_bytes(plaintext_data)

    encrypted_file = tmp_path / "data.txt.age"
    decrypted_file = tmp_path / "data_decrypted.txt"

    # Encrypt with public key
    encryptor = AgeEncryptor(recipient_public_key=recipient_pub)
    encryptor.encrypt_file(str(plaintext_file), str(encrypted_file))

    assert encrypted_file.exists()
    assert encrypted_file.stat().st_size > 0
    # Encrypted content must not contain plaintext string
    assert b"Secret database dump" not in encrypted_file.read_bytes()

    # Decrypt with private key
    AgeEncryptor.decrypt_file(str(encrypted_file), str(decrypted_file), secret_key)

    assert decrypted_file.exists()
    assert decrypted_file.read_bytes() == plaintext_data


def test_decrypt_with_key_file(tmp_path):
    identity = pyrage.x25519.Identity.generate()
    recipient_pub = str(identity.to_public())
    secret_key = str(identity)

    key_file = tmp_path / "key.txt"
    key_file.write_text(f"# Age secret key\n{secret_key}\n")

    input_file = tmp_path / "in.bin"
    input_file.write_bytes(b"hello world")
    enc_file = tmp_path / "in.bin.age"
    dec_file = tmp_path / "out.bin"

    AgeEncryptor(recipient_pub).encrypt_file(str(input_file), str(enc_file))
    AgeEncryptor.decrypt_file(str(enc_file), str(dec_file), str(key_file))

    assert dec_file.read_bytes() == b"hello world"


def test_encrypt_missing_recipient(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("test")
    enc = AgeEncryptor(recipient_public_key=None)
    with pytest.raises(CryptoError):
        enc.encrypt_file(str(f), str(tmp_path / "out.age"))
