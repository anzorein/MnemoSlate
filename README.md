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
    config.py             # lee env/.env
    db.py                 # SQLite: ideas + cola trabajos (encolado/enviado/hecho/error)
    develop.py            # parser /desarrollar: + combina, ,/espacio lotea, & extra
    lore.py               # prompt OpenCode + .md con frontmatter Fuente #IDs (sin hardware)
    bot.py                # handlers /anotar /ideas /desarrollar(encola) + voz + texto libre
    __main__.py           # python -m mnemoslate
  data/                   # ideas.db (gitignored, RF-4.2)
  libro_lore/             # .md por categoria (Fase 3 Syncthing)
  tests/test_db.py tests/test_develop.py tests/test_lore.py
```

Falta con hardware real: `src/mnemoslate/infra/` (ping/WoL/apagado, Fase 1),
sender SSH/API que consuma la cola hacia OpenCode (Fase 4), transcripción de voz.

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
