# MnemoSlate

Sistema distribuido de worldbuilding: captura móvil (Telegram) → Raspberry Pi 24/7 → PC pesada (OpenCode) → Syncthing.

Esta PC es **solo desarrollo**. Producción del bot: Raspberry Pi.

## Estructura (Fase 2)

```
MnemoSlate/
  Requerimientos.txt
  estado_proyecto.md      # memoria entre sesiones/PCs (ver §5 de Requerimientos)
  requirements.txt
  .env.example -> .env    # BOT_TOKEN, ALLOWED_USER_ID (nunca commitear)
  src/mnemoslate/
    config.py             # lee env/.env (Settings del bot + InfraSettings de red)
    db.py                 # SQLite: ideas + cola trabajos (encolado/enviado/hecho/error)
    develop.py            # parser /desarrollar: + combina, ,/espacio lotea, & extra
    lore.py               # prompt OpenCode + .md con frontmatter Fuente #IDs (sin hardware)
    bot.py                # handlers /anotar /ideas /desarrollar(encola) + voz + texto libre
    infra/                # Fase 1: red y energía (solo stdlib, corre en la Pi)
      wol.py              # Magic Packet: normalizar MAC, armar y enviar (RF-2.2)
      net.py              # ping + espera de arranque + cálculo de broadcast (RF-2.1/2.3)
      power.py            # apagado/suspensión remota por SSH (RF-2.4)
      __main__.py         # CLI: --info --ping --wake --wait --ciclo --shutdown
    __main__.py           # python -m mnemoslate
  data/                   # ideas.db (gitignored, RF-4.2)
  libro_lore/             # .md por categoria (Fase 3 Syncthing)
  tests/test_db.py tests/test_develop.py tests/test_lore.py
     tests/test_wol.py tests/test_net.py
```

Falta: conector de la cola hacia OpenCode (Fase 4, SSH/API), transcripción de voz,
Syncthing (Fase 3).

## Fase 1: Wake-on-LAN (configurar en la PC de escritorio)

Requisitos, todos verificables:

- **BIOS** (ASUS Prime B450M-A): `Advanced → APM Configuration → Power On By PCI-E`
  = `Enabled`, y `ErP Ready` = `Disabled` (ErP apaga la NIC en S5 y mata el WoL).
- **Windows** (Administrador de dispositivos → NIC Ethernet → Propiedades):
  - `Administración de energía`: "Permitir que este dispositivo reactive el
    equipo" + **"Solo permitir Magic Packet"** (si no, cualquier paquete de la red
    despierta la PC y se rompe RNF-1).
  - `Opciones avanzadas`: `Wake on Magic Packet` = `Enabled`,
    `Wake on Pattern Match` = `Enabled`, `Energy Efficient Ethernet` = `Disabled`.
- **Sin inicio rápido**: `powercfg /h off` (desactiva el inicio rápido y la
  hibernación; sin esto la PC no despierta desde S5 de forma fiable).
- **Router**: reserva DHCP para la IP de la PC, y Pi y PC en la misma subred
  (sin aislamiento de clientes/AP isolation).
- Verificación: con la PC apagada el LED del RJ45 tiene que quedar encendido.

## Fase 1: probar desde la Raspberry

```bash
export PYTHONPATH=src
python -m mnemoslate.infra --info     # muestra MAC/IP/broadcast y los IPs locales
python -m mnemoslate.infra --ping     # RF-2.1 ¿responde?
python -m mnemoslate.infra --wake     # RF-2.2 Magic Packet (broadcast de subred y limitado, puertos 9 y 7)
python -m mnemoslate.infra --ciclo    # ping -> si está apagada: WoL + espera
```

Prueba completa: `shutdown /s /t 0` en la PC (el LED del RJ45 queda encendido) y
desde la Pi `python -m mnemoslate.infra --ciclo`. Debe arrancar en 10-60s.

Códigos de salida: `0` encendida / orden enviada · `1` no respondió en el plazo
(la idea queda *pendiente*, RNF-4) · `2` error de config o hardware.

## Uso dev (sin instalar nada global aún)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # completar BOT_TOKEN y ALLOWED_USER_ID
python -m unittest discover -s tests -v
python -m mnemoslate   # desde raíz, con src en PYTHONPATH según config IDE
```

En Raspy: `DATABASE_PATH=data/ideas.db`, `python -m mnemoslate` bajo systemd.
