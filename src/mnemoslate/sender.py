"""Sender Fase 4: la Pi consume trabajos → PC (`opencode run`) → inbox/ → Telegram → apagado.

Contrato Pi↔PC (ver README "Fase 4: sender"):
1. Pi: `scp` payload.json (prompt scribe + meta) al home del usuario en la PC.
2. Pi: `ssh opencode run --format json [-m modelo] --dir <Edessia> -f payload "<instrucción>"`.
   El prompt viaja en ARCHIVO (`-f`), no en argv (Windows limita argv a ~32k chars).
3. PC: stdout (`--format json`, o texto si algo falla) → la Pi extrae el documento.
4. Pi (single-writer): `envolver_scribe()` + `guardar_lore(inbox)` → ideas a
   `procesada`, trabajo a `hecho`. OpenCode nunca escribe archivos.
5. Pi notifica por Bot API y apaga la PC (RF-2.4). Si la PC no arranca, todo queda
   `pendiente`/`encolado` (RNF-4) y el usuario recibe la alerta.

Todo I/O vive en `Entorno` (inyectable) para testear sin hardware.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import InfraSettings
from .db import (
    Trabajo,
    cambiar_estado,
    marcar_trabajo,
    obtener_idea,
    reclamar_trabajo,
)
from .lore import build_scribe_prompt, envolver_scribe, extracto, guardar_lore

log = logging.getLogger("mnemoslate.sender")

TIMEOUT_SSH = 15.0
OPENCODE_TIMEOUT = 600.0

INSTRUCCION_CORTA = (
    "Desarrolla el lore del payload adjunto en formato scribe.pf2.tools. "
    "Devuelve SOLO el documento."
)


class NoHayPC(RuntimeError):
    """La PC no respondió al ciclo ping→WoL→wait (RF-2.3, queda pendiente)."""


class ErrorEnvio(RuntimeError):
    """Falló el scp/ssh/opencode con la PC ya encendida."""


@dataclass
class Resultado:
    trabajo_id: int
    ok: bool
    mensaje: str
    archivos: list[str] = field(default_factory=list)


def comando_ssh_generico(host: str, usuario: str, llave: str, remoto: str) -> list[str]:
    """argv ssh con las mismas opciones duras que power.comando_ssh (testeable)."""
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={int(TIMEOUT_SSH)}",
        *(["-i", llave] if llave else []),
        f"{usuario}@{host}",
        remoto,
    ]


def comando_scp(host: str, usuario: str, llave: str,
                origen_local: str, destino_remoto: str) -> list[str]:
    """argv scp Pi→PC. `destino_remoto` con espacios se entrecomilla."""
    dest = f'"{destino_remoto}"' if " " in destino_remoto else destino_remoto
    return [
        "scp",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={int(TIMEOUT_SSH)}",
        *(["-i", llave] if llave else []),
        origen_local,
        f"{usuario}@{host}:{dest}",
    ]


def comando_opencode_remoto(edessia_pc_dir: str, payload_remoto: str,
                            modelo: str = "") -> str:
    """Comando que corre EN la PC (cmd). Rutas con espacios entrecomilladas."""
    ed = f'"{edessia_pc_dir}"' if " " in edessia_pc_dir else edessia_pc_dir
    pl = f'"{payload_remoto}"' if " " in payload_remoto else payload_remoto
    modelo_flag = f" -m {modelo}" if modelo.strip() else ""
    return (
        f'opencode run --format json{modelo_flag} --dir {ed} -f {pl} '
        f'"{INSTRUCCION_CORTA}"'
    )


def extraer_texto_salida(stdout: str) -> str:
    """Extrae el documento de `opencode run --format json` (defensivo).

    Intenta parsear eventos JSON por línea y juntar campos de texto; si nada
    parsea, devuelve el stdout crudo. El formato exacto de eventos se fija en
    el e2e real (ver README); esta función ya tolera ambos.
    """
    textos: list[str] = []
    for linea in stdout.splitlines():
        linea = linea.strip()
        if not linea.startswith("{"):
            continue
        try:
            obj = json.loads(linea)
        except json.JSONDecodeError:
            continue
        _juntar_texto(obj, textos)
    if textos:
        return "\n".join(textos).strip()
    return stdout.strip()


def _juntar_texto(obj: object, salida: list[str]) -> None:
    if isinstance(obj, dict):
        for clave, valor in obj.items():
            if clave in ("text", "content", "output", "message") and isinstance(valor, str):
                if valor.strip():
                    salida.append(valor)
            else:
                _juntar_texto(valor, salida)
    elif isinstance(obj, list):
        for item in obj:
            _juntar_texto(item, salida)


def notificar_telegram(token: str, chat_id: int, texto: str,
                       timeout: float = 15.0) -> bool:
    """POST a Bot API con stdlib. Nunca lanza: el aviso no puede romper el pipeline."""
    try:
        data = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": texto}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001 - notificar es best-effort
        log.warning("No se pudo notificar por Telegram: %s", e)
        return False


@dataclass
class Entorno:
    """I/O inyectable. Por defecto, implementaciones reales (Pi con ssh/scp)."""
    asegurar_pc: object = None
    enviar_payload: object = None
    correr_opencode: object = None
    borrar_remoto: object = None
    apagar: object = None
    notificar: object = None


def entorno_real(infra: InfraSettings, token: str, chat_id: int) -> Entorno:
    """Entorno de producción (corre en la Pi). Importa infra acá para no pesar en tests."""
    from .infra.net import broadcast_de, esperar_activa, ping
    from .infra.power import apagar_pc
    from .infra.wol import enviar_multiples

    def asegurar_pc() -> None:
        if ping(infra.pc_ip, timeout=infra.ping_timeout):
            return  # ya arriba: no se toca (RNF-1)
        broadcast = infra.pc_broadcast or broadcast_de(infra.pc_ip)
        enviar_multiples(infra.pc_mac, broadcast)
        if not esperar_activa(infra.pc_ip, timeout=infra.wake_timeout,
                              intervalo=infra.ping_timeout):
            raise NoHayPC(f"La PC no arrancó en {infra.wake_timeout}s.")

    def enviar_payload(contenido: str, remoto: str) -> None:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            f.write(contenido)
            local = f.name
        try:
            proc = subprocess.run(
                comando_scp(infra.pc_ip, infra.ssh_user, infra.ssh_key, local, remoto),
                capture_output=True, timeout=60)
        finally:
            Path(local).unlink(missing_ok=True)
        if proc.returncode != 0:
            detalle = (proc.stderr or b"").decode(errors="replace").strip()
            raise ErrorEnvio(f"scp falló: {detalle or proc.returncode}")

    def correr_opencode(remoto_payload: str) -> str:
        remoto = comando_opencode_remoto(infra.edessia_pc_dir, remoto_payload,
                                         infra.opencode_model)
        try:
            proc = subprocess.run(
                comando_ssh_generico(infra.pc_ip, infra.ssh_user, infra.ssh_key, remoto),
                capture_output=True, timeout=OPENCODE_TIMEOUT)
        except FileNotFoundError as e:
            raise ErrorEnvio("Sin cliente `ssh` en la Pi.") from e
        except subprocess.TimeoutExpired as e:
            raise ErrorEnvio(f"`opencode run` superó {OPENCODE_TIMEOUT:.0f}s.") from e
        if proc.returncode != 0:
            detalle = (proc.stderr or b"").decode(errors="replace").strip()[-500:]
            raise ErrorEnvio(f"`opencode run` devolvió {proc.returncode}: {detalle}")
        return (proc.stdout or b"").decode(errors="replace")

    def apagar() -> bool:
        return apagar_pc(infra.pc_ip, infra.ssh_user, "shutdown", infra.ssh_key)

    def borrar_remoto(remoto: str) -> None:
        """Limpieza best-effort del payload en la PC (nunca rompe el flujo)."""
        try:
            subprocess.run(
                comando_ssh_generico(infra.pc_ip, infra.ssh_user, infra.ssh_key,
                                     f'del "{remoto}"'),
                capture_output=True, timeout=30)
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo borrar %s en la PC: %s", remoto, e)

    def notificar(texto: str) -> None:
        notificar_telegram(token, chat_id, texto)

    return Entorno(asegurar_pc, enviar_payload, correr_opencode,
                   borrar_remoto, apagar, notificar)


def procesar_trabajo(conn: sqlite3.Connection, infra: InfraSettings,
                     token: str, chat_id: int,
                     entorno: Entorno | None = None) -> Resultado:
    """Un ciclo completo Fase 4 para el trabajo reclamado (UN encendido, N jobs).

    RF-1.5: todos los jobs del trabajo se procesan en el mismo ciclo.
    """
    ent = entorno or entorno_real(infra, token, chat_id)
    trabajo: Trabajo | None = reclamar_trabajo(conn, infra.claim_timeout_min)
    if trabajo is None:
        return Resultado(0, True, "📭 Nada encolado.")

    try:
        ent.asegurar_pc()  # type: ignore[operator]
    except NoHayPC as e:
        # Queda 'enviado' con claim fresco: el timeout lo libera (anti-zombi).
        ent.notificar(f"⚠️ Trabajo #{trabajo.id}: {e} Las ideas siguen pendientes.")  # type: ignore[operator]
        return Resultado(trabajo.id, False, f"⚠️ {e}")

    archivos: list[str] = []
    try:
        for n, job in enumerate(trabajo.jobs, 1):
            ideas = [obtener_idea(conn, i) for i in job]
            if any(i is None for i in ideas):
                faltan = [str(i) for i, idea in zip(job, ideas) if idea is None]
                raise ErrorEnvio(f"IDs inexistentes en job {n}: {', '.join(faltan)}")
            payload = {
                "trabajo": trabajo.id,
                "job": n,
                "fuente": [i.id for i in ideas],  # type: ignore[union-attr]
                "extra": trabajo.extra,
                "prompt": build_scribe_prompt(ideas, trabajo.extra),  # type: ignore[arg-type]
            }
            remoto = f"mnemo_payload_{trabajo.id}_{n}.json"
            ent.enviar_payload(json.dumps(payload, ensure_ascii=False), remoto)  # type: ignore[operator]
            try:
                salida = ent.correr_opencode(remoto)  # type: ignore[operator]
            finally:
                try:
                    ent.borrar_remoto(remoto)  # type: ignore[operator]
                except Exception as e:  # noqa: BLE001 - limpieza best-effort
                    log.warning("Limpieza remota falló: %s", e)
            texto = extraer_texto_salida(salida)
            if not texto:
                raise ErrorEnvio(f"job {n}: `opencode run` no devolvió texto.")
            doc = envolver_scribe(texto, ideas, trabajo.extra)  # type: ignore[arg-type]
            titulo = extracto(ideas[0].contenido, 50) if ideas else f"trabajo-{trabajo.id}"  # type: ignore[union-attr]
            ruta = guardar_lore(Path(infra.inbox_dir), titulo, doc, categoria=None)
            archivos.append(str(ruta))
    except ErrorEnvio as e:
        if trabajo.intentos >= infra.max_intentos:
            marcar_trabajo(conn, trabajo.id, "error")
            ent.notificar(f"❌ Trabajo #{trabajo.id} a 'error' tras {trabajo.intentos} intentos: {e}")  # type: ignore[operator]
        else:
            marcar_trabajo(conn, trabajo.id, "encolado")  # reintento inmediato: la PC está up
            ent.notificar(f"⚠️ Trabajo #{trabajo.id}: {e} (reintento {trabajo.intentos}/{infra.max_intentos})")  # type: ignore[operator]
        return Resultado(trabajo.id, False, f"⚠️ {e}")

    for i in _todos_ids(trabajo):
        cambiar_estado(conn, i, "procesada")
    marcar_trabajo(conn, trabajo.id, "hecho")
    detalle = "\n".join(f"• `{a}`" for a in archivos)
    ent.notificar(f"✅ Trabajo #{trabajo.id} completado:\n{detalle}")  # type: ignore[operator]
    try:
        ent.apagar()  # type: ignore[operator]
    except Exception as e:  # noqa: BLE001 - el trabajo ya está hecho; avisar basta
        log.warning("No se pudo apagar la PC: %s", e)
        ent.notificar(f"⚠️ Trabajo #{trabajo.id} listo pero no pude apagar la PC: {e}")  # type: ignore[operator]
    return Resultado(trabajo.id, True, f"✅ Trabajo #{trabajo.id}: {len(archivos)} archivo(s).",
                     archivos)


def _todos_ids(trabajo: Trabajo) -> list[int]:
    vistos: list[int] = []
    for job in trabajo.jobs:
        for i in job:
            if i not in vistos:
                vistos.append(i)
    return vistos
