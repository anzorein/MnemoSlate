"""Tests del parser /desarrollar (sin dependencias externas)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mnemoslate.develop import ParseError, parse_desarrollar  # noqa: E402


class TestParser(unittest.TestCase):
    def test_simple(self):
        p = parse_desarrollar("#42")
        self.assertEqual(p.jobs, [[42]])
        self.assertEqual(p.extra, "")

    def test_combinado(self):
        p = parse_desarrollar("#12 + #42")
        self.assertEqual(p.jobs, [[12, 42]])
        self.assertTrue(p.es_combinado)

    def test_lote_comas(self):
        p = parse_desarrollar("#40, #41, #42")
        self.assertEqual(p.jobs, [[40], [41], [42]])
        self.assertTrue(p.es_lote)

    def test_lote_espacios_y_sin_numeral(self):
        p = parse_desarrollar("#40 #41 42")
        self.assertEqual(p.jobs, [[40], [41], [42]])

    def test_espacios_alrededor_de_mas_no_parten(self):
        for texto in ("#12 + #42", "#12 +42", "#12+ #42", "#12+#42", "#12  +  #42"):
            with self.subTest(texto=texto):
                self.assertEqual(parse_desarrollar(texto).jobs, [[12, 42]])

    def test_coma_manda_sobre_espacios(self):
        p = parse_desarrollar("#12, #13 + #14")
        self.assertEqual(p.jobs, [[12], [13, 14]])
        self.assertEqual(p.es_lote, True)
        self.assertEqual(p.es_combinado, True)

    def test_mas_mal_colocado(self):
        for malo in ["#12 +", "+ #5", "#12 + + #3", "#12 + , #3"]:
            with self.assertRaises(ParseError, msg=malo):
                parse_desarrollar(malo)

    def test_extra(self):
        p = parse_desarrollar("#42 & brainstorm de 3 criaturas")
        self.assertEqual(p.jobs, [[42]])
        self.assertEqual(p.extra, "brainstorm de 3 criaturas")

    def test_mixto(self):
        p = parse_desarrollar("#12, #13 + #14 & historia corta")
        self.assertEqual(p.jobs, [[12], [13, 14]])
        self.assertEqual(p.extra, "historia corta")

    def test_errores(self):
        for malo in ["", "   ", "& solo extra", "#", "#12 +", "+ #5", "#0", "hola"]:
            with self.assertRaises(ParseError, msg=malo):
                parse_desarrollar(malo)


if __name__ == "__main__":
    unittest.main()
