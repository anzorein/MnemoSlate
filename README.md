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
    db.py                 # SQLite: tabla ideas, IDs #N, estados
    develop.py            # parser /desarrollar: + combina, ,/espacio lotea, & extra
    bot.py                # handlers /anotar /ideas /desarrollar + voz + texto libre
    __main__.py           # python -m mnemoslate
  data/                   # ideas.db (gitignored, RF-4.2)
  libro_lore/             # carpeta Syncthing (Fase 3)
  tests/test_db.py tests/test_develop.py
```

Futuro (no crear aún): `src/mnemoslate/infra/` (ping/WoL/apagado, Fase 1),
`src/mnemoslate/lore.py` (conector SSH/API a OpenCode que consumirá el plan, Fase 4).

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
