"""
core/auth_manager.py
Handles encrypted credential storage (user_id + password only).
API key is NOT stored here — it is always read from the .env file at runtime.
"""
import os
import json
import base64
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


CREDS_FILE = Path.home() / ".mstock_trader" / "credentials.enc"
SALT_FILE  = Path.home() / ".mstock_trader" / "salt.bin"


def _ensure_dir():
    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _get_machine_key() -> bytes:
    import socket
    entropy = f"{socket.gethostname()}:{os.getlogin()}:mstock_v1".encode()
    return hashlib.sha256(entropy).digest()


def _get_or_create_salt() -> bytes:
    _ensure_dir()
    if SALT_FILE.exists():
        return SALT_FILE.read_bytes()
    salt = os.urandom(16)
    SALT_FILE.write_bytes(salt)
    return salt


def _derive_fernet(passphrase: bytes) -> Fernet:
    salt = _get_or_create_salt()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase))
    return Fernet(key)


def save_credentials(user_id: str, password: str, api_key: str = "", access_token: str = ""):
    """
    Encrypt and persist user_id + password to disk.
    api_key param kept for backward compatibility but is NOT stored —
    it is always loaded from .env at runtime.
    """
    _ensure_dir()
    passphrase = _get_machine_key()
    fernet = _derive_fernet(passphrase)
    data = json.dumps({
        "user_id": user_id,
        "password": password,
        # api_key intentionally omitted — stored in .env, not here
        "access_token": access_token,
    }).encode()
    CREDS_FILE.write_bytes(fernet.encrypt(data))


def load_credentials() -> dict | None:
    """Load and decrypt credentials. Returns None if not found."""
    if not CREDS_FILE.exists():
        return None
    try:
        passphrase = _get_machine_key()
        fernet = _derive_fernet(passphrase)
        data = fernet.decrypt(CREDS_FILE.read_bytes())
        return json.loads(data.decode())
    except Exception:
        return None


def update_access_token(access_token: str):
    """Update only the access token in stored credentials."""
    creds = load_credentials()
    if creds:
        save_credentials(
            creds["user_id"],
            creds["password"],
            access_token=access_token,
        )


def clear_credentials():
    """Wipe stored credentials."""
    if CREDS_FILE.exists():
        CREDS_FILE.unlink()
