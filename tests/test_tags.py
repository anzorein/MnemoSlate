"""Tests de micro-etiquetado (sin hardware, stdlib)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mnemoslate.db import (  # noqa: E402
    crear_idea,
    etiquetas_de_idea,
    etiquetar_idea,
    ideas_por_etiqueta,
    init_db,
    listar_etiquetas,
)
from mnemoslate.tags import (  # noqa: E402
    candidatas_por_texto,
    extraer_tags,
    sugerir_parecidos,
)


class TestExtraccion(unittest.TestCase):
    def test_trailing_se_recorta(self):
        limpio, tags = extraer_tags("muro de obsidiana #lugares")
        self.assertEqual((limpio, tags), ("muro de obsidiana", ["lugares"]))

    def test_numeros_son_solo_id(self):
        limpio, tags = extraer_tags("ver #42 y #12 + #42")
        self.assertEqual((limpio, tags), ("ver #42 y #12 + #42", []))

    def test_digito_final_no_se_recorta(self):
        limpio, tags = extraer_tags("texto #lugares #42")
        self.assertEqual(limpio, "texto #lugares #42")
        self.assertEqual(tags, ["lugares"])

    def test_dedupe_y_case(self):
        limpio, tags = extraer_tags("mezcla #Lugares #lugares #magia")
        self.assertEqual(tags, ["lugares", "magia"])
        self.assertEqual(limpio, "mezcla")

    def test_solo_tags_deja_vacio(self):
        limpio, tags = extraer_tags("#magia")
        self.assertEqual(limpio, "")
        self.assertEqual(tags, ["magia"])


class TestFuzzy(unittest.TestCase):
    def test_sugiere_typo(self):
        self.assertEqual(sugerir_parecidos("lugarrs", ["lugares", "magia"]), ["lugares"])

    def test_sin_parecido(self):
        self.assertEqual(sugerir_parecidos("zzzz", ["lugares"]), [])

    def test_existente_no_sugiere(self):
        self.assertEqual(sugerir_parecidos("lugares", ["lugares"]), [])

    def test_candidatas_hook(self):
        self.assertEqual(
            candidatas_por_texto("nómades del vidrio", ["vidrio", "magia"]), ["vidrio"]
        )


class TestDBTags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = init_db(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_roundtrip_y_conteos(self):
        a = crear_idea(self.conn, 1, "muro alto")
        b = crear_idea(self.conn, 1, "runa vieja")
        etiquetar_idea(self.conn, a, ["lugares", "magia"])
        etiquetar_idea(self.conn, b, ["lugares"])
        self.assertEqual(sorted(etiquetas_de_idea(self.conn, a)), ["lugares", "magia"])
        conteos = dict(listar_etiquetas(self.conn))
        self.assertEqual(conteos, {"lugares": 2, "magia": 1})
        por_tag = ideas_por_etiqueta(self.conn, "lugares")
        self.assertEqual([i.id for i in por_tag], [b, a])  # DESC

    def test_reetiquetar_es_idempotente(self):
        a = crear_idea(self.conn, 1, "x")
        etiquetar_idea(self.conn, a, ["a", "a", "A"])
        self.assertEqual(etiquetas_de_idea(self.conn, a), ["a"])


if __name__ == "__main__":
    unittest.main()
