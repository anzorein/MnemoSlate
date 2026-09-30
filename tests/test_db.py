"""Tests de DB sin dependencias externas (corren en PC dev y Raspy)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mnemoslate.db import (  # noqa: E402
    avanzar_hilo,
    cambiar_estado,
    crear_hilo,
    crear_idea,
    encolar_trabajo,
    extracto,
    init_db,
    listar_ideas,
    listar_trabajos,
    obtener_hilo,
    obtener_hilo_por_idea,
    obtener_idea,
    reclamar_trabajo,
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


class TestHilos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = init_db(Path(self.tmp.name) / "t.db")
        self.idea = crear_idea(self.conn, 1, "idea con hilo")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_crud_hilo(self):
        hid = crear_hilo(self.conn, self.idea)
        h = obtener_hilo(self.conn, hid)
        self.assertIsNotNone(h)
        assert h is not None
        self.assertEqual((h.idea_id, h.session_id, h.turno), (self.idea, "", 1))
        self.assertEqual(obtener_hilo_por_idea(self.conn, self.idea).id, hid)  # type: ignore[union-attr]
        self.assertIsNone(obtener_hilo(self.conn, 999))
        self.assertIsNone(obtener_hilo_por_idea(self.conn, 999))

    def test_un_hilo_por_idea(self):
        crear_hilo(self.conn, self.idea)
        with self.assertRaises(Exception):  # UNIQUE(idea_id)
            crear_hilo(self.conn, self.idea)

    def test_avanzar_hilo(self):
        hid = crear_hilo(self.conn, self.idea)
        self.assertTrue(avanzar_hilo(self.conn, hid, "ses_abc"))
        h = obtener_hilo(self.conn, hid)
        assert h is not None
        self.assertEqual((h.turno, h.session_id), (2, "ses_abc"))
        # sin sesión nueva: turno sube, sesión vieja se conserva
        self.assertTrue(avanzar_hilo(self.conn, hid))
        h = obtener_hilo(self.conn, hid)
        assert h is not None
        self.assertEqual((h.turno, h.session_id), (3, "ses_abc"))
        self.assertFalse(avanzar_hilo(self.conn, 999))

    def test_trabajo_lleva_hilo_id(self):
        hid = crear_hilo(self.conn, self.idea)
        tid = encolar_trabajo(self.conn, 1, [[self.idea]], extra="feedback",
                              hilo_id=hid)
        t = reclamar_trabajo(self.conn)
        assert t is not None
        self.assertEqual((t.id, t.hilo_id, t.extra), (tid, hid, "feedback"))
        sueltos = [x for x in listar_trabajos(self.conn) if x.hilo_id == 0]
        self.assertTrue(all(x.id != tid for x in sueltos))
        # trabajo suelto (default) sigue en 0
        tid2 = encolar_trabajo(self.conn, 1, [[self.idea]])
        t2 = [x for x in listar_trabajos(self.conn, "encolado") if x.id == tid2][0]
        self.assertEqual(t2.hilo_id, 0)

    def test_migracion_en_db_vieja(self):
        # DB sin hilos ni hilo_id (pre-sesión 23) se migra al abrir.
        import sqlite3

        ruta = Path(self.tmp.name) / "vieja.db"
        vieja = sqlite3.connect(str(ruta))
        vieja.executescript(
            "CREATE TABLE ideas(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " user_id INTEGER NOT NULL, contenido TEXT NOT NULL,"
            " estado TEXT NOT NULL DEFAULT 'pendiente');"
            "CREATE TABLE trabajos(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " jobs_json TEXT NOT NULL, extra TEXT NOT NULL DEFAULT '',"
            " estado TEXT NOT NULL DEFAULT 'encolado', user_id INTEGER NOT NULL);"
        )
        vieja.commit()
        vieja.close()
        conn = init_db(ruta)
        try:
            cols = {r["name"] for r in
                    conn.execute("PRAGMA table_info(trabajos)").fetchall()}
            self.assertIn("hilo_id", cols)
            tablas = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            self.assertIn("hilos", tablas)
            conn.execute("INSERT INTO ideas(user_id, contenido) VALUES (1,'x')")
            conn.commit()
            hid = crear_hilo(conn, 1)
            self.assertTrue(avanzar_hilo(conn, hid, "s"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
