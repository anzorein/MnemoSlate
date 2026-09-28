"""Bot de Telegram — Fase 2 + parser /desarrollar (RF-1.1 / RF-1.2 / RF-1.3 / RF-1.4 / RF-1.5).

- /anotar, /idea -> guarda texto en inbox SQLite, responde con #ID (RNF-2: inmediato,
  sin encender la PC).
- /ideas, /inbox -> lista ID + extracto + estado.
- /desarrollar, /lore -> parsea #IDs (+ combina, ,/espacio lotea, & extra) y valida
  contra la DB. STUB Fase 4: NO enciende la PC, solo muestra el plan y mantiene
  las ideas en pendiente (RNF-4).
- Texto libre en chat privado -> también se guarda (captura móvil rápida).
- Voz -> se guarda como tipo 'voz' con marcador de transcripción pendiente
  (la transcripción real con Whisper local se agrega en iteración siguiente).
- Solo responde a ALLOWED_USER_ID (RNF-3). Todo lo demás se ignora en silencio.

Ejecución en Raspberry:
    python -m mnemoslate
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings, load_settings
from .db import crear_idea, formatear_linea, init_db, listar_ideas, obtener_idea
from .develop import USO, ParseError, formatear_plan, parse_desarrollar

log = logging.getLogger("mnemoslate")

AYUDA = (
    "📝 *MnemoSlate* — buzón de worldbuilding\n\n"
    "`/anotar <texto>` — guardar idea (alias: `/idea`)\n"
    "`/ideas` — listar últimas (alias: `/inbox`)\n"
    "`/desarrollar #ID [...]` — plan de lore (alias: `/lore`)\n"
    "  `#12 + #42` combina · `#40, #41` lotea · `& texto` agrega instrucción\n"
    "También podés mandarme texto directamente o una nota de voz.\n\n"
    "Fase 4 pendiente: el plan todavía NO enciende la PC."
)


def _conn(context: ContextTypes.DEFAULT_TYPE) -> sqlite3.Connection:
    return context.application.bot_data["conn"]  # type: ignore[return-value]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]  # type: ignore[return-value]


async def _solo_autorizado(update: Update) -> bool:
    """RNF-3: ignora a cualquier otro usuario."""
    allowed = update.effective_user and update.effective_user.id
    expected: int = update.get_bot()._mnemo_allowed  # type: ignore[attr-defined]
    if allowed != expected:
        if update.effective_message:
            # Silencio total hacia extraños (no filtrar info), solo log.
            log.warning("Acceso denegado de user_id=%s", allowed)
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _solo_autorizado(update):
        return
    await update.effective_message.reply_markdown(AYUDA)  # type: ignore[union-attr]


async def cmd_anotar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/anotar <texto> | /idea <texto> — RF-1.1 + RF-1.2."""
    if not await _solo_autorizado(update):
        return
    texto = " ".join(context.args or []).strip()
    # Soporte: /anotar respondiendo a otro mensaje
    if not texto and update.effective_message.reply_to_message:
        texto = (update.effective_message.reply_to_message.text or "").strip()
    if not texto:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Uso: `/anotar tu idea…`\nEj: `/anotar desierto de cristal que canta`",
            parse_mode="Markdown",
        )
        return
    idea_id = crear_idea(
        _conn(context),
        user_id=update.effective_user.id,  # type: ignore[union-attr]
        contenido=texto,
        tipo="texto",
        message_id=update.effective_message.message_id,  # type: ignore[union-attr]
    )
    # RNF-2: respuesta inmediata, sin I/O pesado.
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"✅ Guardada como #{idea_id} (pendiente)"
    )


async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ideas | /inbox — RF-1.3."""
    if not await _solo_autorizado(update):
        return
    st = _settings(context)
    ideas = listar_ideas(_conn(context), limit=st.ideas_page_size)
    if not ideas:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "📭 Inbox vacío. Mandá `/anotar tu primera idea`."
        )
        return
    lineas = "\n\n".join(formatear_linea(i) for i in ideas)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"📥 Últimas {len(ideas)} ideas:\n\n{lineas}"
    )


async def cmd_desarrollar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/desarrollar | /lore — RF-1.4 + RF-1.5 (stub: parsea y valida, no enciende PC)."""
    if not await _solo_autorizado(update):
        return
    raw = " ".join(context.args or []).strip()
    if not raw:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            USO, parse_mode="Markdown"
        )
        return
    try:
        plan = parse_desarrollar(raw)
    except ParseError as e:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"⚠️ {e}\n\n{USO}", parse_mode="Markdown"
        )
        return
    conn = _conn(context)
    faltantes = [i for i in plan.todos_ids if obtener_idea(conn, i) is None]
    if faltantes:
        txt = ", ".join(f"#{i}" for i in faltantes)
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"⚠️ IDs inexistentes: {txt}\nRevisá con `/ideas`.", parse_mode="Markdown"
        )
        return
    # RNF-4: las ideas quedan pendientes; Fase 4 las tomará vía WoL+SSH.
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"{formatear_plan(plan)}\n\n⏳ Encolado (stub): en Fase 4 esto encenderá la PC. "
        "Ideas en *pendiente*."
    )


async def on_texto_libre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Texto sin comando en privado = anotación directa (captura rápida móvil)."""
    if not await _solo_autorizado(update):
        return
    texto = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not texto:
        return
    idea_id = crear_idea(
        _conn(context),
        user_id=update.effective_user.id,  # type: ignore[union-attr]
        contenido=texto,
        tipo="texto",
        message_id=update.effective_message.message_id,  # type: ignore[union-attr]
    )
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"✅ Guardada como #{idea_id} (pendiente)"
    )


async def on_voz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """RF-1.1 voz: guarda marcador; transcripción real en próxima iteración."""
    if not await _solo_autorizado(update):
        return
    voice = update.effective_message.voice  # type: ignore[union-attr]
    dur = getattr(voice, "duration", "?")
    marcador = f"[nota de voz {dur}s — transcripción pendiente] file_id={voice.file_id}"
    idea_id = crear_idea(
        _conn(context),
        user_id=update.effective_user.id,  # type: ignore[union-attr]
        contenido=marcador,
        tipo="voz",
        message_id=update.effective_message.message_id,  # type: ignore[union-attr]
    )
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"🎙️ Voz guardada como #{idea_id}. Transcripción en próxima versión."
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # RNF-4: loguear, nunca perder la idea ya guardada (el guardado ocurre antes).
    log.exception("Error en handler", exc_info=context.error)


def build_app(settings: Settings) -> "ApplicationBuilder":
    conn = init_db(settings.database_path)
    app = ApplicationBuilder().token(settings.bot_token).build()
    app.bot_data["conn"] = conn
    app.bot_data["settings"] = settings
    app.bot._mnemo_allowed = settings.allowed_user_id  # type: ignore[attr-defined]

    app.add_handler(CommandHandler(["start", "help", "ayuda"], cmd_start))
    app.add_handler(CommandHandler(["anotar", "idea"], cmd_anotar))
    app.add_handler(CommandHandler(["ideas", "inbox"], cmd_ideas))
    app.add_handler(CommandHandler(["desarrollar", "lore"], cmd_desarrollar))
    app.add_handler(MessageHandler(filters.VOICE, on_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_texto_libre))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    settings = load_settings(Path(__file__).resolve().parents[2])
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    log.info("DB en %s | usuario permitido=%s", settings.database_path, settings.allowed_user_id)
    build_app(settings).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
