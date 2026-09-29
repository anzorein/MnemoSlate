"""Bot de Telegram — captura + tags + parser /desarrollar (RF-1.1→RF-1.5).

- /anotar, /idea -> guarda texto en inbox SQLite, responde con #ID (RNF-2: inmediato,
  sin encender la PC). Acepta #tags al final (se recortan del texto guardado).
- /ideas [#tag], /inbox -> lista ID + extracto + estado, opcional filtro por tag.
- /tags, /etiquetas -> etiquetas existentes con conteo.
- /tag #ID -> ver tags · /tag #ID #t1 #t2 -> asignar (crea inexistentes).
- `#123` es siempre ID · `#palabra` es siempre tag.
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

import asyncio
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

from .config import InfraSettings, Settings, load_infra_settings, load_settings
from .db import (
    crear_idea,
    encolar_trabajo,
    etiquetas_de_idea,
    etiquetar_idea,
    formatear_linea,
    ideas_por_etiqueta,
    init_db,
    listar_etiquetas,
    listar_ideas,
    obtener_idea,
)
from .develop import USO, ParseError, formatear_plan, parse_desarrollar
from .sender import procesar_trabajo
from .tags import extraer_tags, normalizar_tag, sugerir_parecidos

log = logging.getLogger("mnemoslate")

AYUDA = (
    "📝 *MnemoSlate* — buzón de worldbuilding\n\n"
    "`/anotar <texto> #tag` — guardar idea (alias: `/idea`)\n"
    "`/ideas [#tag]` — listar últimas o filtrar por tag (alias: `/inbox`)\n"
    "`/tags` — etiquetas existentes con conteo (alias: `/etiquetas`)\n"
    "`/tag #ID` — ver tags de una idea · `/tag #ID #t1 #t2` — asignar\n"
    "`/desarrollar #ID [...]` — plan de lore (alias: `/lore`)\n"
    "  `#12 + #42` combina · `#40, #41` lotea · `& texto` agrega instrucción\n"
    "`/procesar` — corre el trabajo encolado más viejo (enciende la PC)\n"
    "`#123` es siempre ID · `#palabra` es siempre tag (se crea si no existe).\n"
    "También podés mandarme texto directamente o una nota de voz.\n\n"
    "Fase 4 pendiente: el plan todavía NO enciende la PC."
)

USO_TAG = (
    "Uso: `/tag #ID` (ver tags) o `/tag #ID #tag1 #tag2…` (asignar)\n"
    "Ej: `/tag #42` · `/tag #42 #lugares #lore`"
)


def _avisos_typos(existentes: list[str], nuevos: list[str]) -> list[str]:
    """`#lugarrs` nuevo con `#lugares` existente -> aviso (igual se crea)."""
    return [
        f"⚠️ nuevo tag #{t}, ¿quisiste decir #{sugerir_parecidos(t, existentes)[0]}?"
        for t in nuevos
        if t not in existentes and sugerir_parecidos(t, existentes)
    ]


async def _guardar_con_tags(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            texto: str) -> None:
    """Guarda idea extrayendo #tags (recorta corrida final). Responde confirmación."""
    conn = _conn(context)
    limpio, tags = extraer_tags(texto)
    if not limpio:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Falta el texto de la idea (solo mandaste tags).\n"
            "Ej: `/anotar muro de obsidiana #lugares`",
            parse_mode="Markdown",
        )
        return
    avisos = _avisos_typos([n for n, _ in listar_etiquetas(conn)], tags)
    idea_id = crear_idea(
        conn,
        user_id=update.effective_user.id,  # type: ignore[union-attr]
        contenido=limpio,
        tipo="texto",
        message_id=update.effective_message.message_id,  # type: ignore[union-attr]
    )
    if tags:
        etiquetar_idea(conn, idea_id, tags)
    # RNF-2: respuesta inmediata, sin I/O pesado.
    resp = f"✅ Guardada como #{idea_id} (pendiente)"
    if tags:
        resp += f" · 🏷️ {', '.join(tags)}"
    if avisos:
        resp += "\n" + "\n".join(avisos)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        resp
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
    """/anotar <texto> [#tags] | /idea — RF-1.1 + RF-1.2 + tags."""
    if not await _solo_autorizado(update):
        return
    texto = " ".join(context.args or []).strip()
    # Soporte: /anotar respondiendo a otro mensaje
    if not texto and update.effective_message.reply_to_message:
        texto = (update.effective_message.reply_to_message.text or "").strip()
    if not texto:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Uso: `/anotar tu idea… #tag`\nEj: `/anotar desierto de cristal #lugares`",
            parse_mode="Markdown",
        )
        return
    await _guardar_con_tags(update, context, texto)


async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ideas [#tag] | /inbox — RF-1.3 + filtro temático para armar lotes."""
    if not await _solo_autorizado(update):
        return
    st = _settings(context)
    conn = _conn(context)
    filtro = (context.args[0] if context.args else "").lstrip("#").strip().lower()
    if filtro and filtro.isdigit():
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "`#123` es un ID, no un tag. Pedí `/ideas #palabra` o `/ideas` a secas.",
            parse_mode="Markdown",
        )
        return
    if filtro:
        ideas = ideas_por_etiqueta(conn, filtro, limit=st.ideas_page_size)
        titulo = f"🏷️ #{filtro} ({len(ideas)})"
        vacio = f"Sin ideas con #{filtro}. Creá una: `/anotar tu idea #{filtro}`."
    else:
        ideas = listar_ideas(conn, limit=st.ideas_page_size)
        titulo = f"📥 Últimas {len(ideas)} ideas"
        vacio = "📭 Inbox vacío. Mandá `/anotar tu primera idea`."
    if not ideas:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            vacio
        )
        return
    lineas = "\n\n".join(formatear_linea(i) for i in ideas)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"{titulo}:\n\n{lineas}"
    )


async def cmd_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tags | /etiquetas — lista etiquetas existentes con conteo."""
    if not await _solo_autorizado(update):
        return
    pares = listar_etiquetas(_conn(context))
    if not pares:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "Sin etiquetas todavía. Creá una al anotar: `/anotar tu idea #lugares`."
        )
        return
    lineas = "\n".join(f"#{n} ({c})" for n, c in pares)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"🏷️ Etiquetas:\n{lineas}"
    )


async def cmd_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tag #ID — ver tags · /tag #ID #t1 #t2 — asignar (crea inexistentes)."""
    if not await _solo_autorizado(update):
        return
    args = context.args or []
    if not args:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            USO_TAG, parse_mode="Markdown"
        )
        return
    crudo_id = args[0].lstrip("#").strip()
    if not crudo_id.isdigit() or int(crudo_id) <= 0:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"El primer argumento debe ser un #ID.\n\n{USO_TAG}", parse_mode="Markdown"
        )
        return
    idea_id = int(crudo_id)
    conn = _conn(context)
    if obtener_idea(conn, idea_id) is None:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"⚠️ #{idea_id} no existe. Revisá con `/ideas`.", parse_mode="Markdown"
        )
        return
    crudos = args[1:]
    if not crudos:  # solo mostrar
        actuales = etiquetas_de_idea(conn, idea_id)
        txt = ", ".join(f"#{t}" for t in actuales) if actuales else "sin tags"
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            f"🏷️ #{idea_id}: {txt}"
        )
        return
    nuevos: list[str] = []
    for c in crudos:
        if c.lstrip("#").strip().isdigit():
            await update.effective_message.reply_text(  # type: ignore[union-attr]
                f"`#{c.lstrip('#')}` es un ID, no un tag. Solo `#palabra`.",
                parse_mode="Markdown",
            )
            return
        try:
            nuevos.append(normalizar_tag(c))
        except ValueError:
            continue
    avisos = _avisos_typos([n for n, _ in listar_etiquetas(conn)], nuevos)
    etiquetar_idea(conn, idea_id, nuevos)
    actuales = etiquetas_de_idea(conn, idea_id)
    resp = f"🏷️ #{idea_id}: {', '.join(f'#{t}' for t in actuales)}"
    if avisos:
        resp += "\n" + "\n".join(avisos)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        resp
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
    # RNF-4: persiste en cola SQLite; Fase 4 la consumirá vía WoL+SSH. Ideas en pendiente.
    tid = encolar_trabajo(
        conn,
        user_id=update.effective_user.id,  # type: ignore[union-attr]
        jobs=plan.jobs,
        extra=plan.extra,
    )
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"{formatear_plan(plan)}\n\n📋 Trabajo #{tid} encolado: en Fase 4 esto encenderá la PC. "
        "Ideas en *pendiente*."
    )


async def cmd_procesar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/procesar — Fase 4: un ciclo PC para el trabajo encolado más viejo.

    Corre en thread aparte (asyncio.to_thread) para no bloquear el event loop:
    el ciclo tarda minutos (WoL + opencode + apagado).
    """
    if not await _solo_autorizado(update):
        return
    infra: InfraSettings | None = context.application.bot_data.get("infra")
    if infra is None or not infra.ssh_user:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Fase 4 no configurada: falta `SSH_USER`/`SSH_KEY` en el `.env` de la Pi."
        )
        return
    st: Settings = _settings(context)
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Procesando cola (enciendo la PC si hace falta)…"
    )
    res = await asyncio.to_thread(
        procesar_trabajo, _conn(context), infra, st.bot_token, st.allowed_user_id
    )
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        res.mensaje
    )


async def on_texto_libre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Texto sin comando en privado = anotación directa (captura rápida móvil)."""
    if not await _solo_autorizado(update):
        return
    texto = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not texto:
        return
    await _guardar_con_tags(update, context, texto)


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


def build_app(settings: Settings, infra: InfraSettings | None = None) -> "ApplicationBuilder":
    conn = init_db(settings.database_path)
    app = ApplicationBuilder().token(settings.bot_token).build()
    app.bot_data["conn"] = conn
    app.bot_data["settings"] = settings
    app.bot_data["infra"] = infra
    app.bot._mnemo_allowed = settings.allowed_user_id  # type: ignore[attr-defined]

    app.add_handler(CommandHandler(["start", "help", "ayuda"], cmd_start))
    app.add_handler(CommandHandler(["anotar", "idea"], cmd_anotar))
    app.add_handler(CommandHandler(["ideas", "inbox"], cmd_ideas))
    app.add_handler(CommandHandler(["tags", "etiquetas"], cmd_tags))
    app.add_handler(CommandHandler("tag", cmd_tag))
    app.add_handler(CommandHandler(["desarrollar", "lore"], cmd_desarrollar))
    app.add_handler(CommandHandler(["procesar", "procesar_cola"], cmd_procesar))
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
    try:
        infra = load_infra_settings(Path(__file__).resolve().parents[2])
    except RuntimeError as e:
        log.warning("Sin config Fase 1/4 (%s): /procesar deshabilitado.", e)
        infra = None
    log.info("DB en %s | usuario permitido=%s", settings.database_path, settings.allowed_user_id)
    build_app(settings, infra).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
