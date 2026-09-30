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

## 2026-09-29 — Sesión 7 (sender Fase 4 + scribe, dev-only con mocks)
- Ingerido `scribe_markdown_reference.md` (498 líneas, en raíz del repo): scribe usa bloques `title/head/info/note/item`, TOC con `((etiquetas))`, `|`/`/` columnas, `=` página, `%` y `<!-- -->` ocultos. **Sin frontmatter YAML** (lo mostraría literal).
- `lore.py`: `GUIA_SCRIBE` (cheat-sheet para el prompt), `build_scribe_prompt()`, `render_scribe()` (esqueleto con TOC), `envolver_scribe()` (antepone `<!-- MnemoSlate | fuente: #N … -->` oculto), `guardar_lore(..., categoria=None)` escribe plano (para `Edessia/inbox/`).
- `db.py`: `claimed_at`+`intentos` (migración en `init_db`), `reclamar_trabajo()` (toma encolado o enviado expirado), `reencolar_expirados()` (anti-zombi).
- Nuevo `sender.py` (stdlib): `procesar_trabajo()` — reclaim → ciclo infra → scp payload → `opencode run --format json --dir Edessia -f payload` (prompt en archivo, no argv: límite 32k en Windows) → inbox/ → ideas `procesada`, trabajo `hecho` → Telegram `✅` → `--shutdown`. Fallos: reencola o `error` tras MAX_INTENTOS, alerta siempre. `Entorno` inyectable.
- Bot `/procesar|/procesar_cola` vía `asyncio.to_thread` (no bloquea el loop); sin infra SSH configurada avisa.
- `config.py` + `.env.example`: EDESSIA_PC_DIR, OPENCODE_MODEL, INBOX_DIR, CLAIM_TIMEOUT_MIN, MAX_INTENTOS.
- Tests `tests/test_sender.py` (feliz/lote, ciclo caído, reintento, agotamiento, zombi, vacía, extractores, comandos, plantilla scribe).
- Decisiones Edessia: inbox=`Edessia/inbox/` (outputs/ queda scribe-only); sync excluye openspec, obsidian, scripts, caches, pdfs, .gemini. Pendiente (casa): mover .md sueltos de raíz y organizar references/.

## 2026-09-29 — Sesión 8 (apagado condicional + CLI --test)
- Hueco detectado por el usuario: el sender apagaba SIEMPRE, incluso con la PC ya encendida. Ahora `asegurar_pc()->bool` registra si hizo WoL y solo apaga si la encendió ella + `APAGAR_AL_FINALIZAR=1` (nuevo en config + `.env.example`). Telegram: `💤 apagada` vs `🖥️ dejada encendida (motivo)`.
- Nuevo CLI `python -m mnemoslate.sender --test` (pipeline real sin apagar, avisos a stdout) y `--procesar` (completo). Códigos 0/1/2. Fix cp1252→UTF-8 como en infra.
- Tests: matriz (encendí→apaga, ya-arriba→no, flag off→no, test→no) + CLI (vacía OK, sin config error). Fakes devuelven bool.
- Suite: 80/80 OK en `.venv` (telegram solo en venv, nada global). Sin pushear aún.

## 2026-09-29 — Sesión 9 (/comandos + empaquetado + deploy Pi)
- `bot.py`: tabla `COMANDOS` (fuente única); `/help` renderiza desde ella (se eliminó la línea stale "Fase 4 pendiente"); nuevo `/comandos|/cmd` (lista corta para el celu). `tests/test_bot.py`: tabla↔handlers en ambos sentidos (con skip si falta telegram).
- `pyproject.toml` (setuptools src-layout, proyecto `mnemoslate`): `pip install -e .` en el venv → chau `PYTHONPATH` (README actualizado, `export` eliminados).
- `deploy/mnemoslate.service`: plantilla systemd (venv python, EnvironmentFile=.env, Restart=always) + sección Deploy Pi en README.
- README: tabla única "Comandos" (bot + CLIs).

## 2026-09-29 — Sesión 10 (verificación RF-2.4 en la Pi + fix de test)
- **`--shutdown` y `--ciclo` verificados end-to-end en la Pi por el usuario**: con `SSH_USER`/`SSH_KEY` en el `.env` real de la Pi, el apagado remoto por SSH y el ciclo ping→WoL→espera funcionan sobre el hardware real. Cierra la Fase 1 (RF-2.1/2.2/2.3/2.4). No hace falta retestear.
- **Test rojo corregido**: `tests/test_sender.py::TestCLI::test_sin_config_error` fallaba solo en la Pi (`AssertionError: 0 != 2`). Causa: el test limpiaba `os.environ` pero **no** evitaba que `_buscar_env()` (config.py) cargara el `.env` real de la raíz del repo, así que la config "faltante" en realidad existía y el CLI devolvía `0`. Era un problema de **aislamiento del test**, no del producto (en la PC dev, sin `.env`, pasaba por casualidad). Fix: `patch("mnemoslate.config.load_dotenv")` para anular la carga desde `.env` durante el test.
- Reproducido en la PC dev creando un `.env` temporal con placeholders → `0 != 2`; con el fix, **83/83 OK tanto con `.env` como sin él**. El `.env` temporal se borró.
- Nota de entorno: la Pi corre Python 3.11 y la suite se lanzaba con `PYTHONPATH=src`; tras Sesión 9 hay `pyproject.toml` + `pip install -e .`, así que el `PYTHONPATH` ya no es necesario en un venv.

## 2026-09-29 — Sesión 11 (repo de lore + `--test` autocontenido + flags)
- **Decisión: Syncthing FUERA, repo Git local + VPN.** El usuario no quiere instalar
  otra app ni exponer SSH. El lore se versiona en un bare repo en la Pi
  (`~/srv/git/lore.git`) con un checkout (`~/lore`) y layout
  `wiki/ references/ inbox/ outputs/ scribe/`. Desvío anotado en `Requerimientos.txt` RF-4.1.
- **Salida = `outputs/` y es Markdown de REFERENCIA, no scribe.** Scribe queda
  reservado para `scribe/` (docs ya pulidos → PDF) más adelante. Nueva pareja en
  `lore.py`: `build_referencia_prompt()` / `envolver_referencia()`; `envolver_scribe()`
  y `render_scribe()` quedan intactos para esa promoción futura.
  `guardar_lore()` gana `prefijo` (nombres `test-…`).
- **`config.py`**: `INBOX_DIR` (default `inbox`), `OUTPUTS_DIR` (nuevo, default
  `outputs`), `SCRIBE_DIR` (nuevo, reservado). `sender.py` escribe en `outputs_dir`.
- **`--test` pasó a ser autocontenido**: DB temporal con `IDEA_PRUEBA` (la escena
  de las clases sociales, ~200 palabras), **nunca toca `data/ideas.db`**, escribe en
  el `outputs/` real con prefijo `test-` → `test-YYYY-MM-DD-escena-clases-sociales.md`,
  y **nunca apaga la PC**. Se puede repetir sin ensuciar la DB ni el lore.
- **Flags de `infra` renombrados** con alias compatibles: canónicos `--encender`
  (alias `--on`) y `--apagar` (alias `--off`, `--shutdown`); `--suspender` igual;
  `--ciclo` queda como alias legacy **oculto** (`argparse.SUPPRESS`), compartido por
  `dest`, así que `--help` solo muestra los canónicos. Verificado: los 6 flags
  (`--on --off --shutdown --ciclo --encender --apagar`) despachan igual.
- Tests: `_infra()` ahora recibe la raíz y setea `inbox`+`outputs`; se asserts que los
  `.md` caen en `outputs/`; nueva `TestReferencia`; `test_test_cola_vacia_ok` se
  reemplaza por `test_test_autocontenido_ok` (archivo `test-*` + idea canónica en el
  payload) y `test_ejecutar_cli_test_usa_db_temporal` (la DB real queda intacta).
- **Suite: 86/86 OK.** README con sección "Repo de lore" (comandos exactos para crear
  el bare y clonarlo desde la PC) y sección "Fase 4: sender" reescrita.
- **Pendiente**: crear el bare repo en la Pi (comandos en README) y correr el primer
  `python -m mnemoslate.sender --test` real end-to-end.

## 2026-09-29 — Sesión 12 (fix de la instrucción corta antes del e2e)
- **Bug encontrado revisando el flujo**: `INSTRUCCION_CORTA` seguía pidiendo
  "formato scribe.pf2.tools" mientras el payload (`build_referencia_prompt`) pedía
  Markdown de referencia. Prompt y argv se contradecían. Ahora pide explícitamente
  Markdown de referencia, sin frontmatter, sin vallas de código y sin comentarios
  sobre el proceso del modelo.
- Restricción respetada: la instrucción viaja entrecomillada en el `cmd` remoto, así
  que no puede llevar comillas dobles.
- Tests anti-regresión: `test_instruccion_pide_referencia_no_scribe` y
  `test_instruccion_no_rompe_el_comando_remoto`. **Suite: 88/88 OK.**
- Confirmado que el prompt largo no viaja por stdout sino por archivo (`scp` +
  `opencode run -f payload`), así que el límite de argv de Windows (~32k) no aplica.
  El stdout solo trae la salida, con timeout de 600s.
- **Decisión del usuario: seguir con Pi-writer** (la PC no escribe nada; devuelve
  texto y la Pi es la única que arma el `.md`, actualiza la DB y avisa). La variante
  "la PC escribe y commitea" queda descartada por ahora.
- **Pendiente inmediato**: primer `--test` real desde la Pi. Hay que fijar el
  formato exacto de `--format json` mirando la salida cruda.

## 2026-09-29 — Sesión 13 (bug de rutas de `-f` + semántica real de `opencode run`)
- **Bug real encontrado al probar a mano**: el payload lo deja `scp` en el home del
  usuario de la PC, pero `opencode run` resuelve `-f` con
  `path.resolve(--dir ?? root, ruta)` → relativo al `--dir`, un nombre pelado no se
  encuentra y el e2e moría con `File not found`. Fix: `ruta_payload_absoluta()` pasa
  `-f "%USERPROFILE%\mnemo_payload_….json"` (cmd expande; al ser absoluta,
  `path.resolve` la respeta). El payload sigue en el home, no ensucia el repo de lore.
- **Corrección de docs**: `-f` NO significa "leé el prompt de este archivo" sino
  "file(s) to attach to message" (adjunta). El sender y el README lo describían mal.
- **Robustez**: como `-f` adjunta el JSON entero, `INSTRUCCION_CORTA` ahora nombra
  explícitamente el campo `prompt` del adjunto (si no, el modelo no sabe dónde está
  el encargo).
- Nota del usuario al probar: por `ssh` desde bash los backslashes se comen
  (`D:\Docs` → `D:Documents`) y opencode avisa `Failed to change directory`. El
  sender no sufre eso (arma el argv sin shell local), pero queda documentado para
  pruebas manuales.
- Tests anti-regresión nuevos: payload con ruta absoluta, payload siempre
  entrecomillado, instrucción nombra `prompt`. **Suite: 91/91 OK.**
- Hardware anotado para un futuro local: RTX 3070 8GB + 32GB DDR4 → 7–8B Q4 entra
  cómodo; 14B Q4 al límite de VRAM. Mismo flag `-m` vía `OPENCODE_MODEL`.
- **Pendiente inmediato**: primer `--test` real desde la Pi (ver comando manual en
  README "Probar a mano en la PC").

## 2026-09-29 — Sesión 14 (`-f` es glotón: el mensaje tenía que ir primero)
- **Segundo bug real, encontrado por el usuario al probar por `ssh` desde la Pi**:
  `File not found: El`. En `run.ts`, `-f` es `type: "string", array: true`: yargs
  consume como valores del array TODO lo que sigue hasta el próximo flag. Como el
  mensaje iba *después* de `-f`, yargs tomó sus palabras como rutas de archivo y
  reventó en la primera (`El`). No era culpa del quoting del usuario: el orden de
  los argumentos estaba mal en el sender.
- Fix: `comando_opencode_remoto()` ahora emite el mensaje **primero** y deja `-f`
  **al final** (último token), así no hay nada que `-f` pueda tragarse.
- `INSTRUCCION_CORTA` sin caracteres que cmd.exe trata como especiales
  (`( ) & | < > ^ % !`): se había eliminado `---` y ahora lo vigila un test.
- **Sobre `%USERPROFILE%`**: no es elegir dónde mandar el payload, es *decir en
  completo dónde `scp` ya lo puso*. `comando_scp` manda destino sin carpeta
  (`user@host:mnemo_payload_….json`) → cae en el home; como `-f` resuelve relativo
  al `--dir`, hace falta la ruta absoluta. La alternativa (scp directo a la carpeta
  del lore) ensuciaría el repo y exige que esa carpeta sea escribible.
- **Aclarado un error mío**: usé el nombre "lore" para la carpeta de la PC en un
  ejemplo, y no existe. La real es `D:\Documentos\Projects\Edessia`, que ya tiene
  `wiki/ references/ outputs/ scribe/`. No hace falta clonar el repo de lore en la
  PC: `EDESSIA_PC_DIR` apunta ahí y OpenCode lee el lore de ese mismo lugar.
- Tests nuevos: mensaje antes de `-f` y de `--format json`, `-f` último token,
  instrucción sin caracteres hostiles de cmd. **Suite: 93/93 OK.**
- **Pendiente inmediato**: ver la salida real de `opencode run --format json` con
  Big Pickle para fijar `extraer_texto_salida()`.

## 2026-09-29 — Sesión 15 (stdin por ssh: cuelgue silencioso de `opencode run`)
- **Bug REAL del pipeline, encontrado por investigación (aún no observado en el
  `--test` porque el e2e nunca llegó a la llamada remota)**: por `ssh`, el stdin
  remoto es una pipe cuyo extremo escritor nunca cierra. `opencode run` ejecuta
  `await Bun.stdin.text()` cuando stdin no es TTY → **se queda esperando EOF para
  siempre** (opencode#38723; medido: cuelga 5/5 con fifo, responde 10/10 con
  `/dev/null`). En el sender eso era un timeout de 600s por cada job.
- Fix: `stdin=subprocess.DEVNULL` en las **tres** llamadas por ssh (`scp` del
  payload, `opencode run`, `del` de limpieza). Test que verifica las tres.
- **Diagnóstico del `EUNKNOWN: unknown error, read` que reportó el usuario por
  `ssh`**: NO es el bug de la unidad `B:` de Bun (esta PC no tiene `B:`; hay
  C/D/E/N). Comprobado en esta misma PC que `opencode 1.18.33` +
  `opencode/big-pickle` funcionan y responden bien en local. O sea: el fallo es
  del entorno de la sesión `ssh` (no interactiva/no elevada), no del modelo ni de
  los argumentos. Queda pendiente el log de esa sesión.
- **Suite: 94/94 OK.**

## 2026-09-30 — Sesión 16 (payload bajo Edessia + errores que hablan)
- **Decisión del usuario: ni `%USERPROFILE%` ni en tests.** Todo el payload vive
  bajo `<EDESSIA_PC_DIR>`; a lo sumo un subdir `temp/` si se borra después. Como
  `scp` no crea carpetas y el `finally` ya borra tras cada job, el payload va
  suelto en la raíz del lore (opción `temp/` anotada como futura si se quiere la
  raíz prístina).
- **Causa raíz del primer `--test` real (`devolvió 1:` mudo)**: dos cosas juntas.
  (a) `-f "%USERPROFILE%\..."` depende de que el shell remoto expanda `%VAR%`:
  cmd sí, PowerShell no → si el `DefaultShell` de sshd es PowerShell, la ruta viaja
  literal y el archivo no existe. (b) opencode escribe ese `File not found` por
  STDOUT (`UI.error`), no por stderr, y `correr_opencode()` descartaba el stdout
  ante exit ≠ 0. Evidencia diferencial: el comando manual con `-f` relativo al
  `--dir` dio `rc=0` con la escena completa.
- Fix: `ruta_payload_en_lore()` (join con `\`, tolera barra final, sin `%` ni env
  vars); `scp` deposita y `del` limpia esa ruta absoluta; `-f` recibe el nombre
  pelado que resuelve contra el `--dir`. Válido en cmd y PowerShell.
- Fix diagnóstico: ante exit ≠ 0, el `ErrorEnvio` incluye la cola del stdout (con
  fallback a stderr). El próximo fallo se explica solo en el `[notify]`.
- Hallazgo lateral del `salida.txt` manual: con `--dir Edessia`, Big Pickle usó sus
  tools para leer `wiki/04-society-factions.md` y `references/story-structure.md`
  antes de escribir: el modelo se auto-abastece de lore. `salida.txt` se borró de
  la raíz del repo (era un pegado temporal de diagnóstico).
- Tests: `test_payload_vive_en_la_carpeta_del_lore`,
  `test_f_sin_variables_de_entorno`, `test_payload_ida_y_vuelta_en_la_carpeta_del_lore`
  (scp/del absolutos + `-f` pelado + sin `%`), `test_error_opencode_incluye_stdout`;
  eliminados los de `%USERPROFILE%`; fixtures con la ruta real de la PC.
- **Pendiente inmediato**: re-correr `python -m mnemoslate.sender --test` desde la Pi.

## 2026-09-30 — Sesión 17 (tiempos por paso en aviso y mensaje)
- **Pedido del usuario tras el primer `--test` real exitoso** (trabajo #1 completado,
  `test-2026-09-29-escena-clases-sociales.md` en `outputs/`, PC dejada encendida):
  no se veía cuánto tardó cada paso.
- `procesar_trabajo()` mide con `time.monotonic()`: ciclo PC (ping→WoL→wait) y por
  job envío `scp`, `opencode run` y guardado; el apagado `ssh` se mide aparte y se
  agrega al mensaje (el aviso ✅ sale antes de apagar, así que no lo incluye).
- `formatear_duracion()` (`4.2s`, `1m23s`, `1h02m`) + `bloque_tiempos()` (`⏱️`
  con líneas por paso + `Total`). Va en el aviso ✅ de Telegram y en el mensaje del
  CLI; ante fallo (`NoHayPC`, `ErrorEnvio`) el mensaje trae el tiempo transcurrido.
- Los tests existentes usan `assertIn`, así que el texto agregado no los rompe.
  Tests nuevos: formato, bloque en mensaje+aviso, `--test` sin línea de apagado,
  fallo con tiempo. **Suite: 100/100 OK.**

## 2026-09-30 — Sesión 18 (idea del `--test` configurable)
- **Pedido del usuario**: poder cambiar el prompt del `--test` sin editar código.
- Nuevas vars `TEST_IDEA`/`TEST_TITULO` en `config.py` + `.env.example` (una sola
  línea cada una). Vacías = la canónica (`IDEA_PRUEBA`/`TITULO_PRUEBA` en
  `sender.py`, única fuente de verdad: `config.py` no la importa para evitar ciclo).
- `_probar_pipeline()` usa `infra.test_idea/test_titulo` con fallback a la canónica.
- Test nuevo: `test_test_usa_idea_configurable` (payload y nombre con los valores
  custom, canónica ausente). **Suite: 101/101 OK.**
- **Pendiente**: `pull` en la Pi; el usuario ya corre `--test` reales exitosos.

## 2026-09-30 — Sesión 19 (sidecar `-thoughts`: la traza fuera del documento)
- **Pedido del usuario**: el `.md` traía TODO el razonamiento previo y lo que el
  modelo había mirado; eso va a un archivo separado, mismo nombre + `thoughts`.
- Nueva `extraer_pensamiento()` en `sender.py`: parsea los eventos `--format json`
  y renderiza la traza (pasos con motivo/tokens, `tool_use` con entradas y salidas
  **recortadas a 500 chars** para no duplicar el lore, fallback genérico para otros
  eventos). **Excluye los eventos de texto** (son el documento) y devuelve `""`
  con stdout plano → en ese caso no se genera archivo.
- `procesar_trabajo()` guarda por job el documento + `<titulo>-thoughts.md` en
  `outputs/` (mismo `prefijo`, p. ej. `test-…-thoughts.md`); ambos van en `archivos`
  y salen en el aviso ✅.
- Tests: `test_pensamiento_separa_traza_del_documento` (documento no duplicado,
  traza con tool/path/motivo/tokens y recorte), `test_pensamiento_vacio_sin_traza`,
  `test_sidecar_thoughts_por_job` (2 archivos por job, ambos existen). Los tests
  viejos con salida plana siguen dando los mismos conteos. **Suite: 104/104 OK.**

