"""Carga de configuración desde variables de entorno / .env.

La Raspberry Pi solo necesita el .env. Sin puertos públicos (RNF-3).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv es opcional en runtime mínimo
    def load_dotenv(*a, **k):  # type: ignore
        return False


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_user_id: int
    database_path: Path
    log_level: str = "INFO"
    ideas_page_size: int = 10


def load_settings(root: Path | None = None) -> Settings:
    root = root or Path.cwd()
    # Busca .env en raíz del proyecto y en cwd (PC dev vs Raspy)
    for candidate in (root / ".env", Path.cwd() / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
            break
    else:
        load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    user = os.getenv("ALLOWED_USER_ID", "").strip()
    db_path = os.getenv("DATABASE_PATH", "data/ideas.db").strip()

    if not token or token.startswith("123456"):
        raise RuntimeError("BOT_TOKEN no configurado. Copiá .env.example a .env.")
    if not user.isdigit():
        raise RuntimeError("ALLOWED_USER_ID no configurado (ID numérico de Telegram).")

    return Settings(
        bot_token=token,
        allowed_user_id=int(user),
        database_path=Path(db_path),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        ideas_page_size=int(os.getenv("IDEAS_PAGE_SIZE", "10")),
    )
