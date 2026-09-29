"""Wake-on-LAN: armado y envío del Magic Packet (RF-2.2).

Un Magic Packet son 102 bytes: 6 bytes de sincronización (0xFF) seguidos de la
MAC destino repetida 16 veces. Se manda por UDP al broadcast de la subred (o al
broadcast limitado 255.255.255.255) en los puertos 9 (discard) o 7 (echo).

Requisitos puestos en la PC (ASUS Prime B450M-A + Realtek RTL8111H):
- BIOS: `Power On By PCI-E` = Enabled, `ErP Ready` = Disabled.
- Windows: "Permitir que este dispositivo reactive el equipo" + "Solo permitir
  Magic Packet", `Wake on Magic Packet` = Enabled, y `powercfg /h off`.
Con eso el LED del RJ45 queda encendido en S5 y la NIC acepta el paquete.
"""
from __future__ import annotations

import re
import socket
from typing import Iterable, Sequence

MAGIC_SYNC = b"\xff" * 6
REPETICIONES = 16
TAMANO_PAQUETE = len(MAGIC_SYNC) + 6 * REPETICIONES  # 102
PUERTOS_POR_DEFECTO = (9, 7)
TIMEOUT_SOCKET = 3.0

# Acepta AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, aabbccddeeff y notación Cisco.
_MAC_FORMATO = re.compile(r"\A(?:[0-9A-Fa-f]{2}[:.\-]){5}[0-9A-Fa-f]{2}\Z|\A[0-9A-Fa-f]{12}\Z")


def normalizar_mac(mac: str) -> bytes:
    """'11-22-33-44-55-66' -> b'\x11\x22\x33\x44\x55\x66'.

    Acepta ':', '-', '.' o sin separadores, en mayúsculas o minúsculas.
    Lanza ValueError con el formato esperado si no puede interpretar la MAC.
    """
    texto = (mac or "").strip()
    if not _MAC_FORMATO.match(texto):
        raise ValueError(
            f"MAC inválida: {mac!r}. Formatos aceptados: "
            "AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, AABBCCDDEEFF"
        )
    return bytes.fromhex(texto.replace(":", "").replace("-", "").replace(".", ""))


def formatear_mac(mac: str | bytes) -> str:
    """Vuelve a 'AA:BB:CC:DD:EE:FF' para logs y mensajes de Telegram."""
    crudo = mac if isinstance(mac, bytes) else normalizar_mac(mac)
    if len(crudo) != 6:
        raise ValueError(f"MAC inválida: {mac!r} (se esperaban 6 bytes)")
    return ":".join(f"{b:02X}" for b in crudo)


def build_magic_packet(mac: str) -> bytes:
    """Arma los 102 bytes del Magic Packet (puro, testeable sin hardware)."""
    return MAGIC_SYNC + normalizar_mac(mac) * REPETICIONES


def enviar_magic_packet(
    mac: str,
    broadcast: str,
    puerto: int = 9,
    timeout: float = TIMEOUT_SOCKET,
) -> bool:
    """Envía un Magic Packet por UDP. True si el socket aceptó el envío.

    `broadcast` es el broadcast de la subred (ej: 192.0.2.255) o el limitado
    (255.255.255.255). SO_BROADCAST es obligatorio o el envío falla en Linux.
    """
    if not 0 < puerto < 65536:
        raise ValueError(f"Puerto inválido: {puerto}")
    paquete = build_magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        enviados = sock.sendto(paquete, (broadcast, puerto))
    return enviados == len(paquete)


def enviar_multiples(
    mac: str,
    broadcasts: Sequence[str],
    puertos: Iterable[int] = PUERTOS_POR_DEFECTO,
) -> list[tuple[str, int, bool]]:
    """Repite el envío a varias combinaciones broadcast/puerto.

    Devuelve [(broadcast, puerto, ok), ...]. Útil para diagnosticar: algunas
    redes (y algunos switches) se comportan mejor con el broadcast de subred y
    otras con el limitado, o con el puerto 7 en lugar del 9.
    """
    normalizar_mac(mac)  # valida una sola vez, antes de abrir sockets
    resultados: list[tuple[str, int, bool]] = []
    for bc in broadcasts:
        for puerto in puertos:
            try:
                ok = enviar_magic_packet(mac, bc, puerto)
            except OSError:
                ok = False
            resultados.append((bc, puerto, ok))
    return resultados
