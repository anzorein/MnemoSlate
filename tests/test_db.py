"""Tests de DB sin dependencias externas (corren en PC dev y Raspy)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mnemoslate.db import (  # noqa: E402
    cambiar_estado,
    crear_idea,
    extracto,
    init_db,
    listar_ideas,
    obtener_idea,
)


class TestDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = init_db(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_ids_incrementales(self):
        a = crear_idea(self.conn, 1, "primera")
        b = crear_idea(self.conn, 1, "segunda")
        self.assertEqual((a, b), (1, 2))
        self.assertEqual(obtener_idea(self.conn, a).contenido, "primera")

    def test_listar_orden_desc_y_estado(self):
        crear_idea(self.conn, 1, "una")
        crear_idea(self.conn, 1, "dos")
        cambiar_estado(self.conn, 1, "procesada")
        todas = listar_ideas(self.conn)
        self.assertEqual([i.id for i in todas], [2, 1])
        pend = listar_ideas(self.conn, estado="pendiente")
        self.assertEqual([i.id for i in pend], [2])

    def test_extracto(self):
        self.assertLessEqual(len(extracto("a " * 100)), 81)


if __name__ == "__main__":
    unittest.main()
