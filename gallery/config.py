"""Config and data-directory handling for Gallery.

All state lives under GALLERY_DATA_DIR (default ~/.gallery):
  gallery.db       - sqlite database
  media/<req_id>/  - uploaded variant files
  config.json      - server settings + bearer token
  logs/            - launchd stdout/stderr (created by deploy, not here)
"""

import json
import os
import secrets
import tempfile
from pathlib import Path

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8787
DEFAULT_URL = "http://bases-mac-mini:8787"


def data_dir() -> Path:
    return Path(os.environ.get("GALLERY_DATA_DIR", str(Path.home() / ".gallery")))


def db_path() -> Path:
    return data_dir() / "gallery.db"


def media_dir() -> Path:
    return data_dir() / "media"


def config_path() -> Path:
    return data_dir() / "config.json"


def atomic_write_json(path: Path, obj: dict) -> None:
    """Write JSON atomically: tempfile -> fsync -> os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"No config at {path}. Run `gallery init` first."
        )
    return json.loads(path.read_text())


def save_config(cfg: dict) -> None:
    atomic_write_json(config_path(), cfg)


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def init_config(force: bool = False) -> dict:
    """Create ~/.gallery/ layout and config.json with a fresh token. Idempotent."""
    data_dir().mkdir(parents=True, exist_ok=True)
    media_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / "logs").mkdir(parents=True, exist_ok=True)

    path = config_path()
    if path.exists() and not force:
        return json.loads(path.read_text())

    cfg = {
        "token": generate_token(),
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "url": DEFAULT_URL,
        "telegram_bot_token": None,
        "telegram_chat_id": None,
    }
    save_config(cfg)
    return cfg


def telegram_creds(cfg: dict) -> tuple[str | None, str | None]:
    """Resolve (bot_token, chat_id): env vars win, else config.json."""
    token = os.environ.get("GALLERY_TELEGRAM_BOT_TOKEN") or cfg.get("telegram_bot_token")
    chat_id = os.environ.get("GALLERY_TELEGRAM_CHAT_ID") or cfg.get("telegram_chat_id")
    return token, chat_id


def client_config() -> tuple[str, str]:
    """Resolve (url, token) for the CLI client: env vars win, else config.json."""
    url = os.environ.get("GALLERY_URL")
    token = os.environ.get("GALLERY_TOKEN")
    if url and token:
        return url.rstrip("/"), token
    cfg = load_config()
    return (url or cfg["url"]).rstrip("/"), (token or cfg["token"])
