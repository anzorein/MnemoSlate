"""Tests de lore .md y cola de trabajos (sin hardware, stdlib)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mnemoslate.db import crear_idea, encolar_trabajo, init_db, listar_trabajos, marcar_trabajo  # noqa: E402
from mnemoslate.lore import build_prompt, guardar_lore, render_markdown, slugify  # noqa: E402
from mnemoslate.db import obtener_idea  # noqa: E402


class TestLore(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Desierto de Cristal!"), "desierto-de-cristal")
        self.assertEqual(slugify("  "), "sin-titulo")

    def test_prompt_y_frontmatter(self):
        tmp = tempfile.TemporaryDirectory()
        conn = init_db(Path(tmp.name) / "t.db")
        a = crear_idea(conn, 1, "desierto que canta")
        b = crear_idea(conn, 1, "nómades del vidrio")
        ideas = [obtener_idea(conn, a), obtener_idea(conn, b)]
        p = build_prompt(ideas, "brainstorm 3 criaturas")
        self.assertIn("#1", p)
        self.assertIn("brainstorm", p)
        md = render_markdown(ideas, "brainstorm", titulo="Nómades")
        self.assertIn('fuente: ["#1", "#2"]', md)
        self.assertIn("Fuente", md)  # sección de trazabilidad
        out = guardar_lore(Path(tmp.name) / "libro", "Nómades", md, categoria="Regiones")
        self.assertTrue(out.exists() and out.suffix == ".md")
        conn.close()
        tmp.cleanup()

    def test_cola_roundtrip(self):
        tmp = tempfile.TemporaryDirectory()
        conn = init_db(Path(tmp.name) / "t.db")
        tid = encolar_trabajo(conn, user_id=1, jobs=[[12, 42], [40]], extra="x")
        self.assertEqual(tid, 1)
        enc = listar_trabajos(conn, estado="encolado")
        self.assertEqual(len(enc), 1)
        self.assertEqual(enc[0].jobs, [[12, 42], [40]])
        self.assertTrue(marcar_trabajo(conn, tid, "hecho"))
        self.assertEqual(listar_trabajos(conn, estado="encolado"), [])
        conn.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
