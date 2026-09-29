# Estado del proyecto MnemoSlate

## 2026-09-28 — Sesión 1 (PC dev, Fase 2 iniciada)
- Leído `Requerimientos.txt`: 4 capas (Bot captura / Raspy energía / PC OpenCode / Syncthing).
- Estructura inicial creada: `src/mnemoslate/{config,db,bot}.py`, `tests/test_db.py`, `data/`, `libro_lore/`.
- Fase 2 base: SQLite `ideas(id AUTOINCREMENT, user_id, message_id, tipo, contenido, estado, created_at, updated_at)` + bot `/anotar|/idea`, `/ideas|/inbox`, texto libre y voz (marcador pendiente de transcripción).
- Pendiente: conseguir BOT_TOKEN (BotFather) + ALLOWED_USER_ID (@userinfobot), probar `python -m unittest`, luego iterar transcripción de voz, `/desarrollar` (Fase 4), WoL/ping (Fase 1), Syncthing (Fase 3).
- Cómo retomar: "Leé estado_proyecto.md y sigamos desde ahí".

## 2026-09-28 — Sesión 2 (PC dev, parser /desarrollar)
- Nuevo `src/mnemoslate/develop.py`: `parse_desarrollar()` (+ combina en un job, ,/espacio lotea jobs, & extra prompting; límites 10 jobs x 10 IDs), `formatear_plan()`, `ParseError`.
- Bot: handler `/desarrollar|/lore` (stub Fase 4, no enciende PC): valida IDs contra DB, avisa faltantes, mantiene pendiente (RNF-4). Ayuda actualizada.
- Tests `tests/test_develop.py`: simple, combinado, lote, extra, mixto, errores.
- Pusheado a `main` de https://github.com/anzorein/MnemoSlate como anzorein.
- Pendiente: BOT_TOKEN en PC dev para smoke test, transcripción voz, conector Fase 4 (SSH/API→OpenCode), Fase 1 (ping/WoL), Fase 3 (Syncthing).

## 2026-09-28 — Sesión 3 (dev-only, sin Pi/PC: cola + lore)
- `db.py`: tabla `trabajos(jobs_json, extra, estado, user_id)` + `encolar/listar/marcar` (migración IF NOT EXISTS, sin romper DBs existentes).
- Nuevo `src/mnemoslate/lore.py` (stdlib): `build_prompt()` (coherencia RF-3.2), `render_markdown()` (frontmatter con fuente #IDs, RF-3.3), `slugify()`, `guardar_lore()` en `libro_lore/<categoria>/FECHA-slug.md`.
- Bot `/desarrollar` ahora persiste `📋 Trabajo #N encolado` en vez de solo mostrar plan.
- Tests `tests/test_lore.py` (prompt, frontmatter, guardado, roundtrip cola). Pusheado a `main`.

## 2026-09-28 — Sesión 4 (Fase 1: red y energía / WoL)
- **Hardware de la PC configurado y verificado**: placa ASUS Prime B450M-A, NIC `Realtek PCIe GbE Family Controller` (RTL8111H) por cable.
  - Red: `Ethernet` = IP `192.0.2.15/24` → broadcast `192.0.2.255`; MAC **`11:22:33:44:55:66`**. IP reservada en el router. Pi y PC en la misma LAN.
  - BIOS: `Advanced → APM Configuration → Power On By PCI-E` = Enabled, `ErP Ready` = Disabled.
  - Windows: NIC → "Permitir que este dispositivo reactive el equipo" + Opciones avanzadas (`Wake on Magic Packet` / `Wake on Pattern Match` Enabled, `Energy Efficient Ethernet` Disabled); `powercfg /h off` (mata el inicio rápido, ya no hace falta desmarcarlo a mano); temporizadores de reactivación del plan de energía OK.
  - **LED del RJ45 encendido con la PC apagada** = capa física lista (ErP no corta la NIC).
- **Nuevo `src/mnemoslate/infra/`** (solo stdlib, pensado para correr en la Pi, sin `pip install wakeonlan`):
  - `wol.py`: `normalizar_mac()` (acepta `:`/`-`/`.`/sin separadores, `ValueError` con formato esperado), `formatear_mac()`, `build_magic_packet()` (102 bytes = `FF×6 + MAC×16`), `enviar_magic_packet()` (UDP con `SO_BROADCAST`), `enviar_multiples()` (varios broadcast × puertos 9 y 7 para compat con switches).
  - `net.py`: `ping()` (flags `-n/-w` en Windows, `-c/-W` en POSIX; nunca lanza por timeout), `esperar_activa()` (RF-2.3, con `dormir`/`al_intentar` inyectados para testear), `broadcast_de()` (calcula el broadcast desde IP/prefijo), `prefijos_locales()`.
  - `power.py` (RF-2.4): `comando_ssh()` construye el argv (`BatchMode=yes`, `ConnectTimeout`), `apagar_pc()` con acciones `shutdown`/`restart`/`suspend`. Usa `shutdown /s /t N` con retardo ≥1 porque `shutdown /t 0` corta la sesión SSH antes de responder; `_parece_cierre_por_apagado()` distingue "la PC se apagó" de un fallo real de SSH. `ErrorApagado` para fallos.
  - `__main__.py`: CLI `python -m mnemoslate.infra` con `--info --ping --wake --wait --ciclo --shutdown --suspender`. Salida `0` ok / `1` no respondió en plazo (queda pendiente, RNF-4) / `2` error de config.
- `config.py`: extraído `_buscar_env()`; nuevo `InfraSettings` + `load_infra_settings()` que **no exige BOT_TOKEN** (la CLI funciona sola). `Settings`/`load_settings()` intactos.
- `.env.example` con los valores reales de la PC y documentación de los requisitos de BIOS/Windows/router.
- **Bug preexistente corregido en `develop.py`** (encontrado al correr los tests): el tokenizer `re.findall(r"#|\d+|\+|,", ...)` descartaba los espacios, así que `#40 #41 #42` se parseaba como **un solo job `[[40,41,42]]`** en vez de lote `[[40],[41],[42]]` como documenta el docstring y exige RF-1.5. Ahora `r"[#,+]|\d+|\s"` conserva los espacios y el espacio separa jobs, con `signo_antes`/`signo_despues`/`es_id` para que los espacios alrededor de `+` **no** partan el job combinado (`#12, #13 + #14` → `[[12],[13,14]]`).
- Tests: `tests/test_wol.py` (normalización, paquete de 102 bytes, envío con socket mockeado, puertos inválidos, envío parcial) y `tests/test_net.py` (ping con `subprocess` mockeado, `esperar_activa` sin esperar, broadcast, comando SSH/apagado). **51 tests, todos verdes.**
- Verificado en la PC dev: `--info` (deriva el broadcast correcto), `--ping` vivo → 0, `--ping` a IP muerta → 1, `--wake` → 4/4 envíos aceptados, `--ciclo` con la PC encendida → "no se toca (RNF-1)".
- Arreglado `UnicodeEncodeError`: en Windows la consola es cp1252 y los emojis rompían la CLI; `main()` fuerza UTF-8 con `errors="replace"`.

### Pendiente para la próxima sesión
1. **Probar WoL real desde la Pi** (lo único que no se puede hacer desde la PC dev): `shutdown /s /t 0` en la PC, y desde la Pi `export PYTHONPATH=src && python -m mnemoslate.infra --ciclo`. Debe arrancar en 10-60s. Después repetir una vez más para confirmar reproducibilidad.
2. Tildar **"Solo permitir Magic Packet"** en la NIC (faltaba) y re-testear: confirma RNF-1 (pings sueltos ya no despiertan la PC).
3. **Fase 4**: `bot.py cmd_desarrollar` debe consumir la cola `trabajos` con el ciclo `ping → wol → esperar → (Fase 4) enviar a OpenCode → apagar` (RF-2.4), manteniendo la idea en *pendiente* si la PC no arranca (RNF-4).
4. OpenSSH Server en la Windows + `SSH_USER`/`SSH_KEY` en el `.env` para habilitar el apagado remoto.
5. Transcripción de voz (Whisper local) y Syncthing (Fase 3).

