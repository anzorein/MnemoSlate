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
  - Red: PC por cable en la LAN del router (subred /24) con la Pi, **IP reservada por DHCP**. Broadcast de la subred = `192.168.x.255` (se deriva solo de `PC_IP` si no lo pones en el `.env`). **Los valores reales de MAC e IP viven únicamente en el `.env` local de cada máquina (gitignoreado) — nunca en archivos versionados.**
  - **Tus datos reales para la PC están en tu `.env` local**: `PC_MAC` (la NIC Ethernet, NO el WiFi USB) y `PC_IP` (la IP reservada en el router). `git grep -i "PC_MAC" -- .` en el repo solo debe devolver la plantilla.
  - BIOS: `Advanced → APM Configuration → Power On By PCI-E` = Enabled, `ErP Ready` = Disabled.
  - Windows: NIC → "Permitir que este dispositivo reactive el equipo" + Opciones avanzadas (`Wake on Magic Packet` / `Wake on Pattern Match` Enabled, `Energy Efficient Ethernet` Disabled); `powercfg /h off` (mata el inicio rápido, ya no hace falta desmarcarlo a mano); temporizadores de reactivación del plan de energía OK.
  - **LED del RJ45 encendido con la PC apagada** = capa física lista (ErP no corta la NIC).
- **Nuevo `src/mnemoslate/infra/`** (solo stdlib, pensado para correr en la Pi, sin `pip install wakeonlan`):
  - `wol.py`: `normalizar_mac()` (acepta `:`/`-`/`.`/sin separadores, `ValueError` con formato esperado), `formatear_mac()`, `build_magic_packet()` (102 bytes = `FF×6 + MAC×16`), `enviar_magic_packet()` (UDP con `SO_BROADCAST`), `enviar_multiples()` (varios broadcast × puertos 9 y 7 para compat con switches).
  - `net.py`: `ping()` (flags `-n/-w` en Windows, `-c/-W` en POSIX; nunca lanza por timeout), `esperar_activa()` (RF-2.3, con `dormir`/`al_intentar` inyectados para testear), `broadcast_de()` (calcula el broadcast desde IP/prefijo), `prefijos_locales()`.
  - `power.py` (RF-2.4): `comando_ssh()` construye el argv (`BatchMode=yes`, `ConnectTimeout`), `apagar_pc()` con acciones `shutdown`/`restart`/`suspend`. Usa `shutdown /s /t N` con retardo ≥1 porque `shutdown /t 0` corta la sesión SSH antes de responder; `_parece_cierre_por_apagado()` distingue "la PC se apagó" de un fallo real de SSH. `ErrorApagado` para fallos.
  - `__main__.py`: CLI `python -m mnemoslate.infra` con `--info --ping --wake --wait --ciclo --shutdown --suspender`. Salida `0` ok / `1` no respondió en plazo (queda pendiente, RNF-4) / `2` error de config.
- `config.py`: extraído `_buscar_env()`; nuevo `InfraSettings` + `load_infra_settings()` que **no exige BOT_TOKEN** (la CLI funciona sola). `Settings`/`load_settings()` intactos.
- `.env.example` con **placeholders** (IP de documentación RFC 5737 y MAC de ejemplo) y documentación de los requisitos de BIOS/Windows/router. Los valores reales de la PC viven **solo** en el `.env` local.
- **Bug preexistente corregido en `develop.py`** (encontrado al correr los tests): el tokenizer `re.findall(r"#|\d+|\+|,", ...)` descartaba los espacios, así que `#40 #41 #42` se parseaba como **un solo job `[[40,41,42]]`** en vez de lote `[[40],[41],[42]]` como documenta el docstring y exige RF-1.5. Ahora `r"[#,+]|\d+|\s"` conserva los espacios y el espacio separa jobs, con `signo_antes`/`signo_despues`/`es_id` para que los espacios alrededor de `+` **no** partan el job combinado (`#12, #13 + #14` → `[[12],[13,14]]`).
- Tests: `tests/test_wol.py` (normalización, paquete de 102 bytes, envío con socket mockeado, puertos inválidos, envío parcial) y `tests/test_net.py` (ping con `subprocess` mockeado, `esperar_activa` sin esperar, broadcast, comando SSH/apagado). **51 tests, todos verdes.**
- Verificado en la PC dev: `--info` (deriva el broadcast correcto), `--ping` vivo → 0, `--ping` a IP muerta → 1, `--wake` → 4/4 envíos aceptados, `--ciclo` con la PC encendida → "no se toca (RNF-1)".
- Arreglado `UnicodeEncodeError`: en Windows la consola es cp1252 y los emojis rompían la CLI; `main()` fuerza UTF-8 con `errors="replace"`.

### Pendiente para la próxima sesión
1. **Probar WoL real desde la Pi** (lo único que no se puede hacer desde la PC dev): `shutdown /s /t 0` en la PC, y desde la Pi `export PYTHONPATH=src && python3 -m mnemoslate.infra --ciclo`. Debe arrancar en 10-60s. Después repetir una vez más para confirmar reproducibilidad.
2. Tildar **"Solo permitir Magic Packet"** en la NIC (faltaba) y re-testear: confirma RNF-1 (pings sueltos ya no despiertan la PC).
3. **Fase 4**: `bot.py cmd_desarrollar` debe consumir la cola `trabajos` con el ciclo `ping → wol → esperar → (Fase 4) enviar a OpenCode → apagar` (RF-2.4), manteniendo la idea en *pendiente* si la PC no arranca (RNF-4).
4. Transcripción de voz (Whisper local) y Syncthing (Fase 3).

## 2026-09-29 — Sesión 5 (RF-2.4: OpenSSH Server en la PC, para el apagado remoto)
- **OpenSSH Server instalado en la PC** (Windows 11 Pro). El capability estaba `NotPresent`; el cliente `ssh.exe` ya venía de fábrica.
  - Servicio `sshd`: `Running` + `StartType=Automatic` (arranca solo al prender la PC, necesario para poder apagarla).
  - Firewall: regla `OpenSSH-Server-In-TCP` habilitada, puerto 22 TCP, perfil **Private** (nunca público → RNF-3). Se verificó que la interfaz `Ethernet` está en categoría `Private`; si estuviera en `Public` la regla no aplicaría.
  - `PubkeyAuthentication` verificado activo (default). **`PasswordAuthentication` sigue habilitado a propósito**: se desactiva recién después de confirmar que la clave entra, para no quedarse sin acceso remoto.
  - Log `OpenSSH/Operational` limpio: sin errores de lectura ni de permisos del archivo de claves.
- **Detalle crítico discovered (el error clásico de Windows)**: el usuario de la PC **es administrador** (en `whoami /groups` el grupo `BUILTIN\Administradores` aparece como *usado solo para denegar* = token no elevado). Para admins, Windows sshd **ignora `~/.ssh/authorized_keys`** y lee `C:\ProgramData\ssh\administrators_authorized_keys`. Poner la clave en el `~/.ssh/` "correcto" simplemente no entra.
  - Clave pública de la Pi instalada ahí, **sin BOM** (`Out-File -Encoding utf8` en PS 5.1 lo mete y sshd lo rechaza → se usó `[IO.File]::WriteAllText` con `UTF8Encoding($false)`).
  - ACL estricta con **SID y no nombres**, porque el Windows está en español y el grupo se llama `Administradores`: `icacls /inheritance:r` + `/grant '*S-1-5-18:F' '*S-1-5-32-544:F'` (SYSTEM y Administrators). Sin esto sshd se niega a leer el archivo.
  - Script idempotente con validación del formato de la clave antes de escribir.
- `power.py` ya estaba preparado para esto: `BatchMode=yes` (nunca pide password → la clave es obligatoria), `StrictHostKeyChecking=accept-new`, y `shutdown /s /t N` con retardo ≥1 para que la orden vuelva antes de que muera la sesión.
- Documentado todo el procedimiento en `README.md` (sección "Fase 1: apagado remoto por SSH") y en `.env.example`, **sin embeber la clave pública ni el nombre de usuario reales** en archivos versionados. La clave pública se pega a mano.
- Verificado: `ssh ... localhost` llega al demonio y ofrece `publickey,password,keyboard-interactive` (el `Permission denied` es lo esperado, la privada está en la Pi).
- **Lado PC validado end-to-end con una clave sonda**: se generó un par efímero en la PC, se agregó temporalmente su pública al archivo de admins, se probó `ssh -i sonda ... whoami` desde la propia PC (**exit 0**, respondió el usuario) y se restauró el archivo dejando **solo** la clave de la Pi (verificado: 1 clave, ACL correcta, primer byte `115` sin BOM). Con esto queda demostrado que el archivo, la ACL y la configuración de `sshd` del lado Windows funcionan; cualquier fallo que quede es exclusivamente del lado Pi (transferencia de la clave o `known_hosts`). La sonda se borró.
- Error que aparece en el primer intento desde la Pi: `Host key verification failed` → **no es un fallo de autenticación**, es que la Pi no conoce la clave de host de la PC. Se resuelve agregando la clave de host correcta a `~/.ssh/known_hosts` en la Pi (obtenida de la propia PC, no vía `ssh-keyscan` a ciegas). `power.py` ya usa `accept-new`, así que el propio `--shutdown` no vuelve a tropezar con esto.
- **`CONEXION_OK` confirmado desde la Pi**: la clave pública instalada coincide y entra sin contraseña.
- **Prueba no destructiva del apagado por SSH** (el riesgo real era que una sesión SSH **no elevada** no tuviera `SeShutdownPrivilege`): se programó `shutdown /s /t 300` **a través de SSH** → `exit 0`, y enseguida se abortó (`shutdown /a` por SSH → `exit 0`; el abort local posterior devolvió `1116 = no había apagado pendiente`, lo que **confirma** que el abort por SSH sí canceló algo). Conclusión: el apagado remoto por SSH funciona; la PC nunca se apagó durante la prueba.
- 51 tests OK.

### Pendiente para la próxima sesión
1. ~~Probar SSH desde la Pi~~ **HECHO**: `CONEXION_OK` confirmado.
2. ~~Desactivar `PasswordAuthentication`~~ **POSPUESTO por decisión del usuario**: `power.py` usa `BatchMode=yes` igual, así que no hace falta para que funcione; el firewall ya lo limita a la LAN. Dejarlo habilitado es una puerta de respaldo. Decidir más adelante.
3. **Probar `python3 -m mnemoslate.infra --shutdown` end-to-end desde la Pi** (apaga la PC de verdad): requiere `SSH_USER` (el usuario de Windows) y `SSH_KEY` (ruta a la privada en la Pi) en el `.env` de la Pi. Recordar que la salida esperada es un `Connection closed` interpretado como éxito, no una salida limpia.
4. **Probar WoL real desde la Pi**: `shutdown /s /t 0` en la PC y desde la Pi `--ciclo`. Debe arrancar en 10-60s; repetir para confirmar reproducibilidad.
5. Tildar **"Solo permitir Magic Packet"** en la NIC y re-testear (RNF-1).
6. **Fase 4**: `bot.py cmd_desarrollar` consumiendo la cola `trabajos` con `ping → wol → esperar → enviar a OpenCode → apagar`.
7. Transcripción de voz (Whisper local) y Syncthing (Fase 3).


## 2026-09-28 — Sesión 6 (dev-only: micro-etiquetado, mergeado con Fase 1)
- Nuevo `src/mnemoslate/tags.py` (stdlib): `#palabra`=tag / `#123`=solo ID; `extraer_tags()` recorta corrida final del contenido; `sugerir_parecidos()` con difflib (cutoff 0.82); `candidatas_por_texto()` como hook futuro de auto-tag (NO cableado aún).
- `db.py`: tablas `etiquetas` + `idea_etiqueta` (UNIQUE, cascade, IF NOT EXISTS) + `etiquetar/etiquetas_de/listar/ideas_por_etiqueta`.
- Bot: helper `_guardar_con_tags()` en `/anotar` y texto libre (reply `✅ #N · 🏷️ tags` + aviso typo); `/tags|/etiquetas` con conteos; `/tag #ID` ver, `/tag #ID #t1 #t2` asignar; `/ideas #tag` filtra (lotes temáticos). Voz fuera (transcribe Groq externo).
- Tests `tests/test_tags.py` (extracción, IDs ignorados, fuzzy, roundtrip). Mergeado vía rebase con Fase 1/SSH.
