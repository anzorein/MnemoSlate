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

    from mnemoslate.bot import COMANDOS, build_app, cmd_seguir, texto_comandos  # noqa: E402
    from mnemoslate.config import Settings  # noqa: E402
    from mnemoslate.db import (  # noqa: E402
        cambiar_estado,
        crear_idea,
        init_db,
        listar_trabajos,
        obtener_hilo_por_idea,
    )

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


class _FakeUser:
    id = 1


class _FakeBot:
    _mnemo_allowed = 1


class _FakeMessage:
    def __init__(self):
        self.respuestas = []

    async def reply_text(self, texto, **kw):
        self.respuestas.append(texto)


class _FakeUpdate:
    effective_user = _FakeUser()

    def __init__(self):
        self.effective_message = _FakeMessage()

    def get_bot(self):
        return _FakeBot()


class _FakeContext:
    def __init__(self, conn, args):
        self.args = args
        self.application = type("App", (), {"bot_data": {"conn": conn}})()


@unittest.skipUnless(HAS_TG, "requiere python-telegram-bot (venv)")
class TestSeguir(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.tmp = tempfile.TemporaryDirectory()
        self.conn = init_db(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    async def _seguir(self, args):
        update = _FakeUpdate()
        ctx = _FakeContext(self.conn, args)
        await cmd_seguir(update, ctx)
        return update.effective_message.respuestas

    async def test_primera_vuelta_pendiente(self):
        a = crear_idea(self.conn, 1, "idea nueva")
        resp = await self._seguir(["#%d" % a, "cambia", "el", "final"])
        self.assertTrue(any("vuelta 1" in r for r in resp), resp)
        h = obtener_hilo_por_idea(self.conn, a)
        self.assertIsNotNone(h)
        assert h is not None
        self.assertEqual(h.turno, 0)  # sin desarrollo previo → primera -v1
        trabajos = listar_trabajos(self.conn, "encolado")
        self.assertEqual(len(trabajos), 1)
        self.assertEqual((trabajos[0].hilo_id, trabajos[0].extra),
                         (h.id, "cambia el final"))

    async def test_primera_vuelta_procesada(self):
        a = crear_idea(self.conn, 1, "idea vieja")
        cambiar_estado(self.conn, a, "procesada")
        resp = await self._seguir(["#%d" % a, "otro", "enfoque"])
        self.assertTrue(any("vuelta 2" in r for r in resp), resp)

    async def test_segunda_vuelta_en_cola_bloqueada(self):
        a = crear_idea(self.conn, 1, "idea")
        await self._seguir(["#%d" % a, "primero"])
        resp = await self._seguir(["#%d" % a, "segundo"])
        self.assertTrue(any("ya tiene una vuelta en cola" in r for r in resp), resp)
        self.assertEqual(len(listar_trabajos(self.conn, "encolado")), 1)

    async def test_sintaxis_y_ids(self):
        resp = await self._seguir([])
        self.assertTrue(any("Uso:" in r for r in resp), resp)
        resp = await self._seguir(["#999", "algo"])
        self.assertTrue(any("inexistente" in r for r in resp), resp)
        resp = await self._seguir(["#1"])
        self.assertTrue(any("Uso:" in r for r in resp), resp)


if __name__ == "__main__":
    unittest.main()
