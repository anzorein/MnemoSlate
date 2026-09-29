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


@dataclass(frozen=True)
class InfraSettings:
    """Datos de la PC de escritorio para la Fase 1 (red y energía)."""
    pc_mac: str
    pc_ip: str
    pc_broadcast: str = ""
    wol_port: int = 9
    wake_timeout: int = 120
    ping_timeout: int = 2
    ssh_user: str = ""
    ssh_key: str = ""
    # --- Sender Fase 4 / Edessia ---
    edessia_pc_dir: str = r"D:\Documentos\Projects\Edessia"  # --dir de opencode en la PC
    opencode_model: str = ""      # vacío = el default de la PC (provider/model)
    # Carpetas del repo de lore (bare local + checkout; ver README "Repo de lore").
    inbox_dir: str = "inbox"      # entrada cruda/manual (ideas, pedidos de brainstorming)
    outputs_dir: str = "outputs"  # salidas de OpenCode: Markdown de REFERENCIA (interim)
    scribe_dir: str = "scribe"    # reservado: docs pulidos listos para PDF (más adelante)
    claim_timeout_min: int = 30   # anti-zombi: reencolar enviados sin resultado
    max_intentos: int = 3         # pasados N intentos el trabajo va a 'error'
    apagar_al_finalizar: bool = True  # False = jamás apagar (seguro para tests)


def _buscar_env(root: Path | None) -> None:
    """Carga el .env de la raíz del proyecto o del cwd (PC dev vs Raspy)."""
    base = root or Path.cwd()
    for candidate in (base / ".env", Path.cwd() / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
            return
    load_dotenv()


def load_settings(root: Path | None = None) -> Settings:
    _buscar_env(root)

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


def load_infra_settings(root: Path | None = None) -> InfraSettings:
    """Carga la config de red/energía. NO exige BOT_TOKEN (CLI usable sola)."""
    _buscar_env(root)

    mac = os.getenv("PC_MAC", "").strip()
    ip = os.getenv("PC_IP", "").strip()
    if not mac:
        raise RuntimeError("PC_MAC no configurado. Copiá .env.example a .env.")
    if not ip:
        raise RuntimeError("PC_IP no configurado (IP reservada de la PC en el router).")

    return InfraSettings(
        pc_mac=mac,
        pc_ip=ip,
        pc_broadcast=os.getenv("PC_BROADCAST", "").strip(),
        wol_port=int(os.getenv("WOL_PORT", "9")),
        wake_timeout=int(os.getenv("WAKE_TIMEOUT", "120")),
        ping_timeout=int(os.getenv("PING_TIMEOUT", "2")),
        ssh_user=os.getenv("SSH_USER", "").strip(),
        ssh_key=os.getenv("SSH_KEY", "").strip(),
        edessia_pc_dir=os.getenv("EDESSIA_PC_DIR", r"D:\Documentos\Projects\Edessia").strip(),
        opencode_model=os.getenv("OPENCODE_MODEL", "").strip(),
        inbox_dir=os.getenv("INBOX_DIR", "inbox").strip(),
        outputs_dir=os.getenv("OUTPUTS_DIR", "outputs").strip(),
        scribe_dir=os.getenv("SCRIBE_DIR", "scribe").strip(),
        claim_timeout_min=int(os.getenv("CLAIM_TIMEOUT_MIN", "30")),
        max_intentos=int(os.getenv("MAX_INTENTOS", "3")),
        apagar_al_finalizar=os.getenv("APAGAR_AL_FINALIZAR", "1").strip().lower()
        not in ("0", "false", "no", "off"),
    )
