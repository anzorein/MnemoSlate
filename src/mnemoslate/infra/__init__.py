"""Infraestructura de red y energía — Fase 1 (RF-2.1 / RF-2.2 / RF-2.3 / RF-2.4).

Vive en la Raspberry Pi (24/7). Solo stdlib: en la Pi no hace falta instalar
`wakeonlan` ni `netifaces`.

    wol.py    -> Magic Packet (encender la PC)
    net.py    -> ping y espera de arranque (comprobar disponibilidad)
    power.py  -> apagado/suspensión remota por SSH (apagar cuando no se usa)
    __main__  -> CLI de diagnóstico: `python -m mnemoslate.infra --encender`

requisitos de hardware (ya configurados en la PC de escritorio):
- BIOS: `Power On By PCI-E` = Enabled, `ErP Ready` = Disabled.
- Windows: NIC -> "Permitir que este dispositivo reactive el equipo" + "Solo
  permitir Magic Packet", y `powercfg /h off` (sin inicio rápido).
- Router: reserva DHCP para la IP de la PC.
"""
