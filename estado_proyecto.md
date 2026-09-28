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
