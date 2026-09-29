"""Sender Fase 4: la Pi consume trabajos → PC (`opencode run`) → outputs/ → Telegram → apagado.

Contrato Pi↔PC (ver README "Fase 4: sender"):
1. Pi: `scp` payload.json (prompt de referencia + meta) al home del usuario en la PC.
2. Pi: `ssh opencode run --format json [-m modelo] --dir <Edessia> -f payload "<instrucción>"`.
   El prompt viaja en ARCHIVO (`-f`), no en argv (Windows limita argv a ~32k chars).
3. PC: stdout (`--format json`, o texto si algo falla) → la Pi extrae el documento.
4. Pi (single-writer): `envolver_referencia()` + `guardar_lore(outputs)` → ideas a
   `procesada`, trabajo a `hecho`. OpenCode nunca escribe archivos.
   La salida es Markdown de REFERENCIA (interim): scribe/PDF queda para más adelante.
5. Pi notifica por Bot API y apaga la PC (RF-2.4). Si la PC no arranca, todo queda
   `pendiente`/`encolado` (RNF-4) y el usuario recibe la alerta.

Todo I/O vive en `Entorno` (inyectable) para testear sin hardware.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import InfraSettings, load_infra_settings
from .db import (
    Trabajo,
    cambiar_estado,
    crear_idea,
    encolar_trabajo,
    init_db,
    marcar_trabajo,
    obtener_idea,
    reclamar_trabajo,
)
from .lore import build_referencia_prompt, envolver_referencia, extracto, guardar_lore

log = logging.getLogger("mnemoslate.sender")

TIMEOUT_SSH = 15.0
OPENCODE_TIMEOUT = 600.0

INSTRUCCION_CORTA = (
    "Desarrolla el lore del payload adjunto en formato scribe.pf2.tools. "
    "Devuelve SOLO el documento."
)

# Idea canónica de prueba para `--test`: una escena corta, siempre igual. Vive en
# una DB temporal, así que nunca contamina la DB real.
IDEA_PRUEBA = (
    "Think of a very short scene where you can note the discrepancy between "
    "social classes in the empire. Total output must be around 200 words or less."
)
TITULO_PRUEBA = "escena-clases-sociales"


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

    def asegurar_pc() -> bool:
        """True si la encendió ella (hay que apagarla); False si ya estaba arriba."""
        if ping(infra.pc_ip, timeout=infra.ping_timeout):
            return False  # ya arriba: no se toca (RNF-1) y no se apaga después
        broadcast = infra.pc_broadcast or broadcast_de(infra.pc_ip)
        enviar_multiples(infra.pc_mac, broadcast)
        if not esperar_activa(infra.pc_ip, timeout=infra.wake_timeout,
                              intervalo=infra.ping_timeout):
            raise NoHayPC(f"La PC no arrancó en {infra.wake_timeout}s.")
        return True

    def enviar_payload(contenido: str, remoto: str) -> None:
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
                     entorno: Entorno | None = None,
                     forzar_sin_apagar: bool = False,
                     prefijo: str = "",
                     titulo_forzado: str = "") -> Resultado:
    """Un ciclo completo Fase 4 para el trabajo reclamado (UN encendido, N jobs).

    RF-1.5: todos los jobs del trabajo se procesan en el mismo ciclo.
    La PC solo se apaga si la encendió este ciclo Y `apagar_al_finalizar` sigue
    activo (nunca se apaga una sesión ajena). `forzar_sin_apagar` = modo --test.
    `prefijo` antepone al nombre del archivo en `outputs/` (ej: `test-`).
    `titulo_forzado` fija el título del archivo (principalmente para `--test`).
    """
    ent = entorno or entorno_real(infra, token, chat_id)
    trabajo: Trabajo | None = reclamar_trabajo(conn, infra.claim_timeout_min)
    if trabajo is None:
        return Resultado(0, True, "📭 Nada encolado.")

    try:
        la_encendi: bool = bool(ent.asegurar_pc())  # type: ignore[operator]
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
                "prompt": build_referencia_prompt(ideas, trabajo.extra),  # type: ignore[arg-type]
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
            doc = envolver_referencia(texto, ideas, trabajo.extra,  # type: ignore[arg-type]
                                      nota=f"trabajo #{trabajo.id} job {n}")
            titulo = titulo_forzado or (extracto(ideas[0].contenido, 50) if ideas  # type: ignore[union-attr]
                                       else f"trabajo-{trabajo.id}")
            ruta = guardar_lore(Path(infra.outputs_dir), titulo, doc,
                                categoria=None, prefijo=prefijo)
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
    if forzar_sin_apagar:
        motivo = "modo test: sin apagar"
    elif not la_encendi:
        motivo = "ya estaba encendida"
    elif not infra.apagar_al_finalizar:
        motivo = "APAGAR_AL_FINALIZAR=0"
    else:
        motivo = ""
    if motivo:
        ent.notificar(f"🖥️ Trabajo #{trabajo.id} listo. PC dejada encendida ({motivo}).")  # type: ignore[operator]
        return Resultado(trabajo.id, True,
                         f"✅ Trabajo #{trabajo.id}: {len(archivos)} archivo(s). PC encendida ({motivo}).",
                         archivos)
    try:
        ent.apagar()  # type: ignore[operator]
    except Exception as e:  # noqa: BLE001 - el trabajo ya está hecho; avisar basta
        log.warning("No se pudo apagar la PC: %s", e)
        ent.notificar(f"⚠️ Trabajo #{trabajo.id} listo pero no pude apagar la PC: {e}")  # type: ignore[operator]
        return Resultado(trabajo.id, True,
                         f"✅ Trabajo #{trabajo.id}: {len(archivos)} archivo(s). PC encendida (falló el apagado).",
                         archivos)
    ent.notificar(f"💤 Trabajo #{trabajo.id} listo. PC apagada.")  # type: ignore[operator]
    return Resultado(trabajo.id, True, f"✅ Trabajo #{trabajo.id}: {len(archivos)} archivo(s). PC apagada.",
                     archivos)


def _todos_ids(trabajo: Trabajo) -> list[int]:
    vistos: list[int] = []
    for job in trabajo.jobs:
        for i in job:
            if i not in vistos:
                vistos.append(i)
    return vistos


# --- CLI: python -m mnemoslate.sender --test | --procesar (e2e desde la Pi) ---
# --test: pipeline REAL autocontenido. Usa una DB temporal con la idea canónica
#         (nunca toca la DB real) y escribe en outputs/ con prefijo `test-`.
#         Nunca apaga la PC.
# --procesar: un ciclo real completo sobre la DB real.
# Códigos: 0 ok, 1 trabajo falló, 2 error de config/entorno.

SALIDA_OK = 0
SALIDA_FALLO = 1
SALIDA_ERROR = 2


def _probar_pipeline(infra: InfraSettings, entorno: Entorno | None = None) -> int:
    """--test autocontenido: DB temporal + idea canónica, sin apagar la PC."""
    with tempfile.TemporaryDirectory(prefix="mnemoslate_test_") as tmp:
        conn = init_db(Path(tmp) / "test.db")
        try:
            idea_id = crear_idea(conn, 0, IDEA_PRUEBA)
            encolar_trabajo(conn, 0, [[idea_id]], extra="")
            ent = entorno or entorno_real(infra, "", 0)
            ent.notificar = lambda texto: print(f"[notify] {texto}")  # type: ignore[method-assign]
            res = procesar_trabajo(conn, infra, "", 0, ent,
                                   forzar_sin_apagar=True, prefijo="test-",
                                   titulo_forzado=TITULO_PRUEBA)
        finally:
            conn.close()
    print(res.mensaje)
    for a in res.archivos:
        print(f"  {a}")
    return SALIDA_OK if res.ok else SALIDA_FALLO


def ejecutar_cli(modo: str, db_path: Path, root: Path | None = None,
                 entorno: Entorno | None = None) -> int:
    """Núcleo testeable de la CLI: `modo` = --test (autocontenido) o --procesar."""
    try:  # Windows: la consola es cp1252 y los emojis la rompen (igual que infra)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - si no se puede, se sigue igual
        pass
    try:
        infra = load_infra_settings(root)
    except RuntimeError as e:
        print(f"Config: {e}", file=sys.stderr)
        return SALIDA_ERROR
    try:
        if modo == "--test":
            return _probar_pipeline(infra, entorno)
        conn = init_db(db_path)
        try:
            ent = entorno or entorno_real(infra, "", 0)
            ent.notificar = lambda texto: print(f"[notify] {texto}")  # type: ignore[method-assign]
            res = procesar_trabajo(conn, infra, "", 0, ent)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - la CLI no muere con traceback crudo
        log.exception("Fallo inesperado")
        print(f"Error: {e}", file=sys.stderr)
        return SALIDA_ERROR
    print(res.mensaje)
    for a in res.archivos:
        print(f"  {a}")
    return SALIDA_OK if res.ok else SALIDA_FALLO


def main_cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sender Fase 4 (Pi -> PC -> outputs/).")
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--test", dest="modo", action="store_const", const="--test",
                       help="prueba e2e autocontenida (DB temporal, idea canónica, sin apagar)")
    grupo.add_argument("--procesar", dest="modo", action="store_const",
                       const="--procesar", help="pipeline real completo sobre la DB real")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    return ejecutar_cli(args.modo, Path(os.getenv("DATABASE_PATH", "data/ideas.db")))


if __name__ == "__main__":
    raise SystemExit(main_cli())
