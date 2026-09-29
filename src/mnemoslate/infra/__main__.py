"""CLI de diagnóstico de la Fase 1. Corre igual en la PC dev y en la Raspberry.

    python -m mnemoslate.infra --info                 # muestra la config de red
    python -m mnemoslate.infra --ping                 # RF-2.1: ¿responde la PC?
    python -m mnemoslate.infra --wake                 # RF-2.2: manda el Magic Packet
    python -m mnemoslate.infra --wait                 # RF-2.3: espera el arranque
    python -m mnemoslate.infra --encender             # ping -> si está apagada, WoL + espera
    python -m mnemoslate.infra --apagar               # RF-2.4: apaga la PC por SSH

Alias: `--on` = `--encender`, `--off`/`--shutdown` = `--apagar`, `--suspender`.

Códigos de salida (para usar desde scripts o tests de humo):
    0  la PC está encendida / la orden se envió
    1  la PC no respondió dentro del plazo (queda pendiente, RNF-4)
    2  error de configuración o de hardware

`--encender` es el que automatiza el RF completo: si la PC ya está arriba no la
toca (RNF-1); si está apagada la enciende una sola vez y espera.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ..config import InfraSettings, load_infra_settings
from . import power, wol
from .net import broadcast_de, esperar_activa, ping, prefijos_locales

log = logging.getLogger("mnemoslate.infra")

SALIDA_OK = 0
SALIDA_TIMEOUT = 1
SALIDA_ERROR = 2


def _resolver_broadcast(cfg: InfraSettings) -> str:
    """Usa PC_BROADCAST del .env o, si falta, lo deriva de PC_IP /24."""
    if cfg.pc_broadcast:
        return cfg.pc_broadcast
    derivado = broadcast_de(cfg.pc_ip)
    log.info("PC_BROADCAST vacío: derivo %s desde %s/24", derivado, cfg.pc_ip)
    return derivado


def _info(cfg: InfraSettings) -> int:
    mac = wol.formatear_mac(cfg.pc_mac)
    print("MnemoSlate · configuración de infraestructura (Fase 1)")
    print(f"  PC_MAC       : {mac}")
    print(f"  PC_IP        : {cfg.pc_ip}")
    print(f"  broadcast    : {_resolver_broadcast(cfg)}")
    print(f"  WOL_PORT     : {cfg.wol_port}")
    print(f"  WAKE_TIMEOUT : {cfg.wake_timeout}s")
    print(f"  PING_TIMEOUT : {cfg.ping_timeout}s")
    if cfg.ssh_user:
        print(f"  SSH_USER     : {cfg.ssh_user} (apagado remoto activo)")
    else:
        print("  SSH_USER     : (vacío) -- apagado remoto no configurado")
    print("  IPs locales  : " + ", ".join(prefijos_locales()))
    return SALIDA_OK


def _ping(cfg: InfraSettings) -> int:
    viva = ping(cfg.pc_ip, cfg.ping_timeout)
    print(("🟢" if viva else "🔴") + f" {cfg.pc_ip} {'responde' if viva else 'NO responde'}")
    return SALIDA_OK if viva else SALIDA_TIMEOUT


def _wake(cfg: InfraSettings) -> int:
    broadcast = _resolver_broadcast(cfg)
    mac = wol.formatear_mac(cfg.pc_mac)
    # Se manda al broadcast de subred y al limitado, puertos 9 y 7: máxima
    # compatibilidad con switches/routers que filtran alguno de ellos.
    objetivos = [broadcast]
    limitado = "255.255.255.255"
    if broadcast != limitado:
        objetivos.append(limitado)
    resultados = wol.enviar_multiples(cfg.pc_mac, objetivos, (cfg.wol_port, 7))

    print(f"📡 Magic Packet a {mac}")
    for bc, puerto, ok in resultados:
        print(f"  {'✅' if ok else '❌'} {bc}:{puerto}")
    enviados = sum(1 for _, _, ok in resultados if ok)
    if not enviados:
        print("⚠️  No se pudo enviar por ningún canal. Revisá que la Pi esté en la misma subred.")
        return SALIDA_ERROR
    print(f"   {enviados}/{len(resultados)} envíos aceptados. La PC debería arrancar en 10-60s.")
    return SALIDA_OK


def _wait(cfg: InfraSettings) -> int:
    print(f"⏳ Esperando hasta {cfg.wake_timeout}s a que {cfg.pc_ip} responda…")

    def intento(n: int) -> None:
        log.info("intento %s: ping %s", n, cfg.pc_ip)

    if esperar_activa(cfg.pc_ip, cfg.wake_timeout, al_intentar=intento):
        print(f"🟢 {cfg.pc_ip} respondió. PC encendida.")
        return SALIDA_OK
    print(f"🔴 {cfg.pc_ip} no respondió en {cfg.wake_timeout}s. La idea queda pendiente (RNF-4).")
    return SALIDA_TIMEOUT


def _encender(cfg: InfraSettings) -> int:
    """RF-2.1 + RF-2.2 + RF-2.3 encadenados, sin encender si ya está viva."""
    if ping(cfg.pc_ip, cfg.ping_timeout):
        print(f"🟢 {cfg.pc_ip} ya está encendida. No se toca (RNF-1).")
        return SALIDA_OK
    print(f"🔴 {cfg.pc_ip} está apagada. Enviando Magic Packet…")
    codigo = _wake(cfg)
    if codigo != SALIDA_OK:
        return codigo
    return _wait(cfg)


def _apagar(cfg: InfraSettings) -> int:
    return _orden_remota(cfg, "shutdown", "apagado")


def _suspender(cfg: InfraSettings) -> int:
    return _orden_remota(cfg, "suspend", "suspensión")


def _orden_remota(cfg: InfraSettings, accion: str, nombre: str) -> int:
    if not cfg.ssh_user:
        print(f"⚠️  SSH_USER vacío en el .env: no puedo ordenar el {nombre} remoto.")
        return SALIDA_ERROR
    try:
        ok = power.apagar_pc(cfg.pc_ip, cfg.ssh_user, accion=accion, llave=cfg.ssh_key)
    except (power.ErrorApagado, ValueError) as e:
        print(f"❌ {e}")
        return SALIDA_ERROR
    print(("✅ " if ok else "❌ ") + f"Orden de {nombre} enviada a {cfg.pc_ip}.")
    return SALIDA_OK if ok else SALIDA_ERROR


# (flag canónico, función, ayuda) — el orden importa: de menos a más invasivo.
ACCIONES: list[tuple[str, object, str]] = [
    ("--ping", _ping, "RF-2.1: ¿responde la PC a ping?"),
    ("--wake", _wake, "RF-2.2: envía el Magic Packet (WoL)"),
    ("--wait", _wait, "RF-2.3: espera a que la PC termine de arrancar"),
    ("--encender", _encender, "enciende la PC (ping -> si está apagada, WoL + espera)"),
    ("--apagar", _apagar, "RF-2.4: apaga la PC por SSH"),
    ("--suspender", _suspender, "RF-2.4: suspende la PC por SSH"),
]

# Alias compatibles: `--on`/`--off` cortos para el celu, `--shutdown` histórico.
# `--ciclo` queda como alias legacy OCULTO (no se documenta; nadie "cicla" un equipo).
ALIASES: dict[str, str] = {
    "--on": "--encender",
    "--off": "--apagar",
    "--shutdown": "--apagar",
    "--ciclo": "--encender",
}


def main(argv: list[str] | None = None) -> int:
    # En Windows la consola puede venir en cp1252 y los emojis/acentos revientan
    # con UnicodeEncodeError; forzamos UTF-8 tolerante.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="python -m mnemoslate.infra",
        description="Red y energía de la PC (ping / Wake-on-LAN / encendido / apagado).",
    )
    parser.add_argument("--info", action="store_true", help="muestra la config y sale")
    for flag, _, ayuda in ACCIONES:
        parser.add_argument(flag, action="store_true", help=ayuda, dest=flag.lstrip("-"))
    for alias, canon in ALIASES.items():
        parser.add_argument(alias, action="store_true", help=argparse.SUPPRESS,
                            dest=canon.lstrip("-"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    if not args.info and not any(getattr(args, f.lstrip("-")) for f, _, _ in ACCIONES):
        parser.print_help()
        return SALIDA_ERROR

    try:
        cfg = load_infra_settings(Path(__file__).resolve().parents[3])
    except RuntimeError as e:
        print(f"❌ {e}")
        return SALIDA_ERROR

    if args.info:
        return _info(cfg)
    for flag, accion, _ in ACCIONES:
        if getattr(args, flag.lstrip("-")):
            return accion(cfg)  # type: ignore[operator,return-value]
    return SALIDA_OK


if __name__ == "__main__":
    sys.exit(main())
