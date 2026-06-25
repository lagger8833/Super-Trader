"""
core/env_loader.py
Loads credentials from a .env file.

Search order:
  1. Same folder as the running EXE / main.py  (recommended)
  2. Current working directory
  3. User home directory (~/.super_trader/.env)

.env format:
  API_KEY=your_api_key_here
  CHECKSUM=L

CHECKSUM is the "source" value passed to generate_session().
Per the official mStock Type A docs, this is the literal string "L"
for direct API integrations. Only change it if mStock tells you otherwise.
"""
import os
import sys
from pathlib import Path


def _app_dir() -> Path:
    """Return the directory of the running executable or script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _find_env_file() -> Path | None:
    candidates = [
        _app_dir() / ".env",
        Path.cwd() / ".env",
        Path.home() / ".super_trader" / ".env",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _parse_env_file(path: Path) -> dict:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def load_env_config() -> tuple[str, str, str]:
    """
    Returns (api_key, checksum, source_path).

    api_key  — your mStock API key from trade.mstock.com
    checksum — the 'source' string for generate_session(); defaults to "L"
               (the value documented by mStock for direct API integrations)
    source_path — the .env file that was loaded (for display)

    Raises FileNotFoundError if no .env file found.
    Raises KeyError if API_KEY is missing.
    """
    env_path = _find_env_file()
    if env_path is None:
        raise FileNotFoundError(
            "No .env file found.\n\n"
            f"Create a file named '.env' in:\n  {_app_dir()}\n\n"
            "Contents:\n  API_KEY=your_api_key_here\n  CHECKSUM=L"
        )

    parsed = _parse_env_file(env_path)
    api_key = parsed.get("API_KEY", "").strip()
    if not api_key:
        raise KeyError(
            f"API_KEY not found or empty in:\n  {env_path}\n\n"
            "Make sure the file contains:\n  API_KEY=your_api_key_here"
        )

    # CHECKSUM defaults to "L" — the value in official mStock docs for
    # direct (non-partner) API integrations. Override only if mStock advises.
    checksum = parsed.get("CHECKSUM", "L").strip() or "L"

    return api_key, checksum, str(env_path)


# Convenience wrapper kept for backward compatibility
def load_api_key() -> tuple[str, str]:
    api_key, _, source = load_env_config()
    return api_key, source


def get_env_file_path() -> str:
    return str(_app_dir() / ".env")
