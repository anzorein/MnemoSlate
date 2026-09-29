"""Apagado / suspensión remota de la PC por SSH (RF-2.4, RNF-1).

La PC se enciende solo para procesar un lote de ideas y se apaga después, para
no desperdiciar energía. Desde la Raspberry se manda la orden con el cliente
`ssh` del sistema (sin dependencias Python extra) apuntando al OpenSSH Server de
la PC, que corre solo en la red local (RNF-3: no se abre ningún puerto público).

Detalle importante de Windows: `shutdown /s /t 0` mata la sesión SSH antes de
que el comando responda, y el cliente ve una conexión cerrada / error de
transporte aunque el apagado sí se haya ejecutado. Por eso se usa un retardo
(`/t N`, N >= 1) que le da tiempo al comando a volver con éxito, y el
resultado se interpreta con tolerancia a ese cierre abrupto.
"""
from __future__ import annotations

import shlex
import subprocess

TIMEOUT_SSH = 15.0

ACCIONES = {
    # /t con retardo: devuelve antes de que la PC se apague (ver docstring).
    "shutdown": "shutdown /s /t {retardo}",
    "restart": "shutdown /r /t {retardo}",
    # SetSuspendState 0 = suspender (1 = hibernar, no disponible con powercfg /h off).
    "suspend": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
}

RETARDO_MINIMO = 1


class ErrorApagado(RuntimeError):
    """Fallo al intentar apagar la PC de forma remota."""


def comando_ssh(
    host: str,
    usuario: str,
    accion: str = "shutdown",
    llave: str = "",
    retardo: int = 5,
) -> list[str]:
    """Construye el argv de ssh. Separado para poder testear sin red."""
    if accion not in ACCIONES:
        raise ValueError(f"Acción inválida: {accion}. Usá: {', '.join(ACCIONES)}")
    if retardo < RETARDO_MINIMO and accion in ("shutdown", "restart"):
        raise ValueError(f"El retardo debe ser >= {RETARDO_MINIMO} para no cortar la sesión SSH.")
    remoto = ACCIONES[accion].format(retardo=retardo)
    return [
        "ssh",
        "-o", "BatchMode=yes",       # sin prompt de contraseña (RNF-3)
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={int(TIMEOUT_SSH)}",
        *(["-i", llave] if llave else []),
        f"{usuario}@{host}",
        remoto,
    ]


def apagar_pc(
    host: str,
    usuario: str,
    accion: str = "shutdown",
    llave: str = "",
    retardo: int = 5,
    timeout: float = TIMEOUT_SSH,
) -> bool:
    """Manda la orden de apagado por SSH. True si la orden se aceptó.

    `host` es la IP de la PC, `usuario` el usuario de Windows con OpenSSH
    Server habilitado, `llave` la ruta a la clave privada si se usa una.
    """
    argv = comando_ssh(host, usuario, accion, llave, retardo)
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout + retardo)
    except FileNotFoundError as e:
        raise ErrorApagado("No se encontró el cliente `ssh` en la Raspberry.") from e
    except subprocess.TimeoutExpired as e:
        raise ErrorApagado(f"La PC no respondió el SSH en {timeout + retardo:.0f}s.") from e
    if proc.returncode == 0:
        return True
    detalle = (proc.stderr or b"").decode(errors="replace").strip()
    # Sesión SSH cortada por el propio apagado: la orden igual se ejecutó.
    if retardo >= RETARDO_MINIMO and _parece_cierre_por_apagado(detalle):
        return True
    raise ErrorApagado(f"SSH devolvió {proc.returncode}: {detalle or 'sin detalle'}")


def _parece_cierre_por_apagado(detalle: str) -> bool:
    """Distingue 'la PC se apagó' de 'ssh falló de verdad'."""
    marcas = (
        "connection closed",
        "connection reset",
        "closed by remote host",
        "error in libcrypto",
        "kex_exchange_identification",
        "broken pipe",
        "recv failure",
    )
    bajo = detalle.lower()
    return any(m in bajo for m in marcas)


def resumir_comando(argv: list[str]) -> str:
    """Version legible de un argv, para logs (no expone la llave)."""
    return " ".join(shlex.quote(a) for a in argv if a)
