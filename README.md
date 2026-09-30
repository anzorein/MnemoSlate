# MnemoSlate

Sistema distribuido de worldbuilding: captura móvil (Telegram) → Raspberry Pi 24/7 → PC pesada (OpenCode) → repo de lore (Git local, sincronizado por la VPN).

Esta PC es **solo desarrollo**. Producción del bot: Raspberry Pi.

## Estructura

```
MnemoSlate/
  Requerimientos.txt
  estado_proyecto.md      # memoria entre sesiones/PCs (ver §5 de Requerimientos)
  scribe_markdown_reference.md  # sintaxis scribe.pf2.tools (outputs/ → PDF)
  requirements.txt + pyproject.toml  # deps + editable (chau PYTHONPATH)
  .env.example -> .env    # BOT_TOKEN, ALLOWED_USER_ID (nunca commitear)
  deploy/mnemoslate.service  # plantilla systemd para la Pi (Restart=always)
   src/mnemoslate/
    config.py             # lee env/.env (Settings bot + InfraSettings red/sender)
    db.py                 # SQLite: ideas + trabajos (claim/intentos) + etiquetas
    develop.py            # parser /desarrollar: + combina, ,/espacio lotea, & extra
    tags.py               # #palabra=tag/#123=ID, fuzzy anti-typo, hook auto-tag futuro
    lore.py               # prompts + plantillas scribe/markdown (single-writer: la Pi)
    sender.py             # Fase 4: cola → ciclo PC → opencode → outputs/ → notify → off
                          # + CLI: --test (autocontenido, sin apagar) / --procesar
    bot.py                # /anotar /ideas[#tag] /tags /tag /desarrollar /procesar
                          # /comandos (índice, fuente única COMANDOS) + voz
    infra/                # Fase 1: red y energía (solo stdlib, corre en la Pi)
      wol.py              # Magic Packet: normalizar MAC, armar y enviar (RF-2.2)
      net.py              # ping + espera de arranque + cálculo de broadcast (RF-2.1/2.3)
      power.py            # apagado/suspensión remota por SSH (RF-2.4)
      __main__.py         # CLI: --info --ping --wake --wait --encender --apagar
    __main__.py           # python -m mnemoslate
  data/                   # ideas.db (gitignored, RF-4.2)
  tests/test_db.py tests/test_develop.py tests/test_lore.py tests/test_tags.py
     tests/test_wol.py tests/test_net.py tests/test_sender.py tests/test_bot.py
```

El **repo de lore** (ver "Repo de lore") es otra cosa: un repo Git local en la Pi
(checkout con `wiki/ references/ inbox/ outputs/ scribe/`) que reemplaza a
Syncthing para sincronizar el material entre la PC y la Pi por la VPN.

Falta con hardware: e2e del sender desde la Pi (`--test`), transcripción de voz
(Groq externo, en la backburner).

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
python -m mnemoslate.infra --info      # muestra MAC/IP/broadcast y los IPs locales
python -m mnemoslate.infra --ping      # RF-2.1 ¿responde?
python -m mnemoslate.infra --wake      # RF-2.2 Magic Packet (broadcast de subred y limitado, puertos 9 y 7)
python -m mnemoslate.infra --encender  # ping -> si está apagada: WoL + espera   (alias --on)
python -m mnemoslate.infra --apagar    # RF-2.4 apaga por SSH                    (alias --off/--shutdown)
```

Prueba completa: `shutdown /s /t 0` en la PC (el LED del RJ45 queda encendido) y
desde la Pi `python -m mnemoslate.infra --encender`. Debe arrancar en 10-60s.

Códigos de salida: `0` encendida / orden enviada · `1` no respondió en el plazo
(la idea queda *pendiente*, RNF-4) · `2` error de config o hardware.

## Fase 1: apagado remoto por SSH (RF-2.4)

Para que la Pi pueda apagar la PC (`python -m mnemoslate.infra --apagar`, alias
`--shutdown`) hace falta OpenSSH Server en la PC, configurado **solo por clave**:

**En la PC (PowerShell como Administrador):**
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service  sshd -StartupType Automatic
Start-Service sshd
# que quede acotado a la red local (perfil Private), nunca público (RNF-3)
New-NetFirewallRule -Name MnemoSlate-SSH -DisplayName 'SSH (LAN)' -Enabled True `
  -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 `
  -Profile Private -RemoteAddress LocalSubnet
```

**En la Raspberry** (la privada nunca sale de acá):
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N "" -C "mnemoslate-pi"
```

**De vuelta en la PC**, instalar la clave pública que imprimiste. Ojo con esto:
si el usuario de Windows **es administrador**, Windows **ignora**
`~/.ssh/authorized_keys` y lee `C:\ProgramData\ssh\administrators_authorized_keys`:

```powershell
# en PowerShell COMO ADMINISTRADOR (la ACL es obligatoria o sshd no lee el archivo)
$pub = 'ssh-ed25519 AAAA... mnemoslate-pi'
[IO.File]::WriteAllText("C:\ProgramData\ssh\administrators_authorized_keys", $pub + "`n", (New-Object Text.UTF8Encoding($false)))
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /inheritance:r
icacls "C:\ProgramData\ssh\administrators_authorized_keys" /grant '*S-1-5-18:F' '*S-1-5-32-544:F'   # SYSTEM y Administrators
Restart-Service sshd
```
> Se usan los SID y no los nombres porque en Windows en español el grupo se llama
> `Administradores`. `WriteAllText` en vez de `Out-File` porque `Out-File -Encoding
> utf8` en PowerShell 5.1 mete BOM y sshd rechaza el archivo.

**Probar desde la Pi** (esto no apaga nada todavía):
```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519 <TU_USUARIO_PC>@<PC_IP> "echo CONEXION_OK"
```

Recién cuando eso responda `CONEXION_OK`, completá `SSH_USER` y `SSH_KEY` en el
`.env` de la Pi y probá `python3 -m mnemoslate.infra --apagar`.

**Detalle de diseño:** el apagado usa `shutdown /s /t N` con `N >= 1`, no `/t 0`.
Con retardo 0 la sesión SSH se corta antes de que el comando responda y el
cliente ve "Connection closed", que se confunde con un fallo. `power.py` además
distingue ese cierre abrupto (que significa "se apagó") de un error real de SSH.

## Repo de lore (PC ↔ Pi, por VPN)

El material de Edessia se versiona en un **repo Git local en la Pi**: no hay
Syncthing, y la Pi solo es alcanzable por la VPN (sin puertos abiertos, RNF-3).

| Carpeta | Qué va |
|---|---|
| `wiki/` | lore yategizado, notas largas |
| `references/` | material de consulta: extractos, resúmenes |
| `inbox/` | entrada cruda/manual: ideas para guardar, pedidos de brainstorming |
| `outputs/` | **salidas de OpenCode**: Markdown de REFERENCIA (interim) |
| `scribe/` | reservado: docs ya pulidos, listos para PDF (más adelante) |

Crear el repo bare en la Pi (una sola vez):

```bash
mkdir -p ~/srv/git && git init --bare ~/srv/git/lore.git
git clone ~/srv/git/lore.git ~/lore && cd ~/lore
mkdir -p wiki references inbox outputs scribe
printf '# Lore de Edessia\n' > README.md
git add . && git commit -m "Estructura inicial del lore"
git branch -M main && git push -u origin main
```

Desde la PC, por VPN:

```bash
git clone <usuario_pi>@<ip_pi>:/home/<usuario_pi>/srv/git/lore.git
```

`INBOX_DIR`, `OUTPUTS_DIR` y `SCRIBE_DIR` del `.env` apuntan a esas carpetas
(por default son `inbox`, `outputs` y `scribe`, relativas a la raíz del checkout).

## Fase 4: sender (Pi → PC → outputs → Telegram → apagado)

Contrato Pi↔PC (`sender.py`, sin puertos públicos, RNF-3):

1. `/desarrollar` encola; `/procesar` reclama el trabajo más viejo (o un `enviado`
   expirado: anti-zombi por `CLAIM_TIMEOUT_MIN`).
2. Ciclo `infra` (ping→WoL→wait). Si la PC no arranca: todo queda pendiente y
   Telegram avisa (RNF-4). La PC nunca se toca si ya está arriba (RNF-1).
3. El prompt largo viaja en **archivo**: `scp mnemo_payload_<trabajo>_<job>.json`
   a la carpeta del lore en la PC + `opencode run "<instrucción>" --format json
   -m <modelo> --dir <EDESSIA_PC_DIR> -f <nombre>`. argv de Windows limita a ~32k
   chars, el lore no entra.
4. OpenCode devuelve **Markdown de referencia** (encabezados y prosa, sin
   frontmatter YAML). Solo la **Pi escribe** en `outputs/` (single-writer).
   La trazabilidad va en `<!-- MnemoSlate | fuente: #N | fecha: … -->`.
   El formato **scribe** (`scribe_markdown_reference.md`) queda reservado para
   cuando el material esté pulido y se quiera pasar a `scribe/` → PDF.
   La traza del proceso (pasos, herramientas, archivos leídos, tokens) NO va en
   el documento: va a un sidecar `<mismo-nombre>-thoughts.md` con salidas
   recortadas. Con stdout plano (sin eventos JSON) no se genera sidecar.
5. Ideas a `procesada`, trabajo a `hecho`, Telegram `✅` con rutas **y tiempos por
   paso** (`ciclo PC`, `scp`, `opencode run`, `guardado`, `Total`; ante fallo, el
   tiempo transcurrido), y apagado **solo si el ciclo la encendió**
   (`APAGAR_AL_FINALIZAR=1`): una PC que ya estaba arriba se deja encendida
   (RNF-1 también al apagar). Telegram dice `💤` o `🖥️`.
   Fallos: reencola (o `error` tras `MAX_INTENTOS`) + alerta siempre.

### `--test`: e2e autocontenido

```bash
python -m mnemoslate.sender --test
```

Corre el pipeline **real** (ping → WoL → scp → `opencode run`) pero:

- usa una **DB temporal** con la idea de prueba (nunca toca `data/ideas.db`);
- escribe en el `outputs/` real con prefijo `test-`
  (`test-YYYY-MM-DD-escena-clases-sociales.md`);
- **nunca apaga la PC**.

La idea y el título salen de `TEST_IDEA`/`TEST_TITULO` del `.env` (una sola línea
cada uno); vacíos = la canónica (`IDEA_PRUEBA`: escena de clases sociales,
~200 palabras).

`--procesar` es el ciclo completo sobre la DB real (y ahí sí vale `APAGAR_AL_FINALIZAR`).

Formato `--format json` (fijado con el e2e real): el documento viaja en partes
`{"type":"text", "part":{"type":"text", "text":"..."}}` y `extraer_texto_salida()`
**solo** toma esas. Las salidas de herramientas (`glob`/`grep`/`read`) se ignoran
para el documento (van recortadas al sidecar `-thoughts`): antes se juntaban sus
`output` y el `.md` arrancaba con listados del lore. JSON sin texto → `""` →
reintento. La instrucción corta que
viaja en argv (`INSTRUCCION_CORTA`) pide **Markdown de referencia**; no puede
contener comillas dobles porque el comando remoto las envuelve.

### Trampas de `opencode run` (encontradas leyendo `run.ts`)

- **`-f` adjunta, no es "leé el prompt de acá".** Es "file(s) to attach to
  message": el archivo entero viaja como adjunto. Por eso `INSTRUCCION_CORTA`
  dice explícitamente que el encargo está en el campo `prompt` del JSON.
- **`-f` se resuelve relativo al `--dir`, y el payload vive ahí.** El código hace
  `path.resolve(--dir ?? root, ruta)`: `scp` deposita el payload directo en la
  carpeta del lore (`ruta_payload_en_lore()`) y `-f` recibe el nombre pelado, que
  resuelve contra el `--dir`. Nada de home, nada de variables de entorno del shell
  remoto: `%VAR%` solo lo expande cmd, y si el `DefaultShell` de sshd es PowerShell
  la variable viaja literal y el archivo no existe. El payload se borra tras cada
  job (`borrar_remoto` en `finally`), así que no ensucia el repo.
- **Backslashes**: si probás a mano por `ssh` desde la Pi, encerrá el comando
  remoto en comillas **simples** o bash se come los `\`
  (`D:\Docs` → `D:Documents`). El sender no sufre esto porque arma el argv sin
  pasar por un shell local.
- **`-f` es glotón y el mensaje va primero.** En `run.ts`, `-f` es
  `type: "string", array: true`: yargs consume como valores del array todo lo que
  sigue hasta el próximo flag. Con el mensaje *después* de `-f`, sus palabras se
  tomaban como rutas y el comando moría con `File not found: El`. Por eso el
  sender emite el mensaje **primero** y deja `-f` **al final** (último token).
- **La instrucción evita caracteres especiales de cmd** (`( ) & | < > ^ % !`), que
  el shell remoto interpretaría. Hay un test que lo vigila.
- **`stdin` cerrado (`DEVNULL`) en toda llamada por `ssh`.** Por `ssh`, el stdin
  remoto es una pipe que nunca cierra, y `opencode run` hace
  `await Bun.stdin.text()` cuando stdin no es TTY: se queda esperando EOF para
  siempre (opencode#38723, reproducido: colgar 5/5 con fifo, responder 10/10 con
  `/dev/null`). El sender manda `stdin=subprocess.DEVNULL` en las tres llamadas
  (`scp`, `opencode`, limpieza) por eso. En una terminal normal no hace falta.
- **`EUNKNOWN: unknown error, read` en Windows por `ssh`** era el `stdin` abierto
  (ver punto anterior): con `ssh -n` o `stdin=DEVNULL` opencode bootea normal.
  Descartado el bug de Bun con la unidad virtual `B:~BUN\root` (esta PC no tiene
  unidad `B:`; hay C/D/E/N).
- **opencode escribe sus errores por stdout.** `File not found: ...` sale por
  `UI.error()` (stdout), no por stderr. Por eso `correr_opencode()` ante exit ≠ 0
  incluye la cola del stdout en el `ErrorEnvio`: si no, el fallo llega mudo
  (un `devolvió 1:` sin nada, como pasó en el primer `--test` real).

### Probar a mano en la PC (sin la Pi)

`payload.json` lo crea la Pi; para replicarlo a mano ponelo en la carpeta lore
(resuelta contra `--dir`):

```json
{"trabajo": 0, "job": 1, "fuente": [1], "extra": "",
 "prompt": "Think of a very short scene where you can note the discrepancy between social classes in the empire. Total output must be around 200 words or less."}
```

```powershell
opencode run "El archivo adjunto es un JSON cuyo campo prompt trae el encargo. Desarrolla ese lore y devuelve SOLO el documento final en Markdown de referencia: encabezados y prosa, sin frontmatter, sin vallas de codigo y sin comentarios sobre tu proceso." --format json -m opencode/big-pickle --dir D:\Documentos\Projects\Edessia -f test-payload.json
```

Desde la Pi por `ssh`, encerrá TODO el comando remoto en comillas **simples**
(así bash no toca los backslashes ni las comillas dobles internas):

```bash
ssh <usuario_pc>@<ip_pc> 'opencode run "El archivo adjunto es un JSON cuyo campo prompt trae el encargo. Desarrolla ese lore y devuelve SOLO el documento final en Markdown de referencia: encabezados y prosa, sin frontmatter, sin vallas de codigo y sin comentarios sobre tu proceso." --format json -m opencode/big-pickle --dir D:\Documentos\Projects\Edessia -f test-payload.json'
```

Modelo: `OPENCODE_MODEL` en el `.env` de la Pi (vacío = default de la PC).
`opencode/big-pickle` es el modelo gratis de OpenCode Zen (razonamiento, 200K ctx).
Cambiar de modelo es **una línea del `.env`**; para privacidad total, `ollama/<modelo>`
local en la PC también entra por el mismo `-m`.

## Comandos (índice)

Bot (desde el celu; `/comandos` los lista, `/help` detalla):

| Comando | Uso |
|---|---|
| `/anotar` (`/idea`) | `/anotar <texto> #tag` — guarda idea |
| `/ideas` (`/inbox`) | `/ideas [#tag]` — últimas o filtro temático |
| `/tags` (`/etiquetas`) | etiquetas existentes con conteo |
| `/tag` | `/tag #ID` ver · `/tag #ID #t1 #t2` asignar |
| `/desarrollar` (`/lore`) | `/desarrollar #ID [...] [& extra]` — encola plan |
| `/procesar` | corre la cola (enciende la PC, apaga solo si la encendió) |
| `/comandos` (`/cmd`) | esta lista · `/start` ayuda completa |

Pi/PC (sin `PYTHONPATH`: con el editable instalado basta el venv activo):

```bash
python -m mnemoslate.infra --info --ping --wake --wait --encender --apagar
python -m mnemoslate.sender --test      # e2e autocontenido (DB temporal, sin apagar)
python -m mnemoslate.sender --procesar  # pipeline real completo
```

Alias de `infra`: `--on`/`--encender` · `--off`/`--shutdown`/`--apagar` ·
`--suspender`.

## Uso dev (nada global: todo en `.venv`)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .   # editable: chau PYTHONPATH para siempre
cp .env.example .env   # completar BOT_TOKEN y ALLOWED_USER_ID
python -m unittest discover -s tests -v
python -m mnemoslate   # desde cualquier cwd del proyecto
```

## Deploy Pi (systemd, una sola vez)

Ver `deploy/mnemoslate.service` (plantilla con los pasos en comentarios):
venv + `pip install -r requirements.txt` + `pip install -e .`, `.env` completo,
`systemctl enable --now mnemoslate`. Restart automático, logs con
`journalctl -u mnemoslate -f`.
