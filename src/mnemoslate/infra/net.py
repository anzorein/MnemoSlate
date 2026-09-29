"""Comprobación de disponibilidad de la PC por ping (RF-2.1) y espera de
arranque (RF-2.3).

Antes de cada trabajo pesado hay que saber si la PC ya está encendida; si no,
se la enciende con WoL y se espera a que responda. Si pasado el plazo no
responde, la idea queda en estado *pendiente* y se avisa al usuario (RNF-4):
esta función solo devuelve False, nunca lanza por timeout.

Sin dependencias: se invoca al binario `ping` del sistema, que existe en la
Raspberry Pi y en Windows ( flags distintos, se detectan con os.name ).
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Callable

TIMEOUT_PING = 2.0
INTERVALO_ESPERA = 5.0
TIMEOUT_SSH = 10.0


def _comando_ping(host: str, timeout: float) -> list[str]:
    """Arma el comando de ping con los flags del sistema operativo."""
    if os.name == "nt":  # Windows: -n cuenta paquetes, -w va en milisegundos
        return ["ping", "-n", "1", "-w", str(max(1, int(timeout * 1000))), host]
    seg = max(1, int(round(timeout)))
    return ["ping", "-c", "1", "-W", str(seg), host]


def ping(host: str, timeout: float = TIMEOUT_PING) -> bool:
    """True si la PC responde a un echo request. Nunca lanza por error de red."""
    if not host or not host.strip():
        return False
    try:
        proc = subprocess.run(
            _comando_ping(host.strip(), timeout),
            capture_output=True,
            timeout=timeout + 2.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def esperar_activa(
    host: str,
    timeout: float = 120.0,
    intervalo: float = INTERVALO_ESPERA,
    dormir: Callable[[float], None] = time.sleep,
    al_intentar: Callable[[int], None] | None = None,
) -> bool:
    """Espera a que la PC responda a ping. True si respondió dentro del plazo.

    Comprueba primero (respuesta inmediata si ya está encendida) y después
    reintenta cada `intervalo` segundos hasta agotar `timeout` (RF-2.3).
    `dormir` y `al_intentar` se inyectan para poder testear sin esperar.
    """
    limite = time.monotonic() + timeout
    intento = 0
    while True:
        intento += 1
        if al_intentar:
            al_intentar(intento)
        if ping(host):
            return True
        if time.monotonic() >= limite:
            return False
        dormir(intervalo)


def broadcast_de(ip: str, prefijo: int = 24) -> str:
    """Calcula el broadcast de la subred: 192.0.2.15/24 -> 192.0.2.255."""
    partes = ip.strip().split(".")
    if len(partes) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in partes):
        raise ValueError(f"IPv4 inválido: {ip!r}")
    if not 0 <= prefijo <= 32:
        raise ValueError(f"Prefijo inválido: {prefijo}")
    numero = 0
    for p in partes:
        numero = (numero << 8) | int(p)
    mascara = (0xFFFFFFFF << (32 - prefijo)) & 0xFFFFFFFF
    direccion = (numero | (~mascara & 0xFFFFFFFF)) & 0xFFFFFFFF
    return ".".join(str((direccion >> desplazamiento) & 0xFF) for desplazamiento in (24, 16, 8, 0))


def prefijos_locales() -> list[str]:
    """IPs de las interfaces locales, para propone un PC_IP si falta el .env."""
    import socket

    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.update({"127.0.0.1"})
    return sorted(ips)
