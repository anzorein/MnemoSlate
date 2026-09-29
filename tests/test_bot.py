"""Tests del índice de comandos (requiere python-telegram-bot: corre en venv).

Garantía: todo CommandHandler registrado está en COMANDOS y viceversa.
Si agregás un comando al bot sin documentarlo (o al revés), esto falla.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from telegram.ext import CommandHandler  # noqa: E402

    from mnemoslate.bot import COMANDOS, build_app, texto_comandos  # noqa: E402
    from mnemoslate.config import Settings  # noqa: E402

    HAS_TG = True
except ImportError:
    HAS_TG = False


@unittest.skipUnless(HAS_TG, "requiere python-telegram-bot (venv)")
class TestComandos(unittest.TestCase):
    def _registrados(self):
        st = Settings(bot_token="123456:fake-test-token", allowed_user_id=1,
                      database_path=Path(":memory:"))
        app = build_app(st, None)
        cmds: set[str] = set()
        for grupo in app.handlers.values():
            for h in grupo:
                if isinstance(h, CommandHandler):
                    cmds.update(h.commands)
        return cmds

    def test_tabla_cubre_handlers(self):
        primarios = {c for c, _, _ in COMANDOS}
        registrados = self._registrados()
        self.assertLessEqual(primarios, registrados,
                             f"sin handler: {primarios - registrados}")

    def test_handlers_cubiertos_por_tabla(self):
        # Alias conocidos (no primarios pero válidos en handlers).
        alias = {"idea", "inbox", "etiquetas", "lore", "procesar_cola",
                 "help", "ayuda", "cmd"}
        primarios = {c for c, _, _ in COMANDOS}
        registrados = self._registrados()
        self.assertLessEqual(registrados, primarios | alias,
                             f"sin documentar: {registrados - primarios - alias}")

    def test_texto_contiene_todo(self):
        txt = texto_comandos()
        for c, _, _ in COMANDOS:
            self.assertIn(f"/{c}", txt)
        self.assertNotIn("Fase 4 pendiente", txt)


if __name__ == "__main__":
    unittest.main()
