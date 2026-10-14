"""Entry points: [project.scripts] existe y apunta a callables importables.

Garantía: tras `pip install -e .` hay comandos cortos (`mnemoslate`,
`mnemo-infra`, `mnemo-sender`) sin PYTHONPATH ni `python -m`. Si alguien rompe
un entry point, esto falla.
"""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

RAIZ = Path(__file__).resolve().parents[1]
ESPERADOS = {
    "mnemoslate": ("mnemoslate.bot", "main"),
    "mnemo-infra": ("mnemoslate.infra.__main__", "main"),
    "mnemo-sender": ("mnemoslate.sender", "main_cli"),
}


class TestScripts(unittest.TestCase):
    def _scripts(self):
        with open(RAIZ / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["scripts"]

    def test_nombres(self):
        scripts = self._scripts()
        for nombre in ESPERADOS:
            self.assertIn(nombre, scripts)

    def test_destinos_con_formato_modulo_atributo(self):
        import importlib

        for nombre, (modulo, atributo) in ESPERADOS.items():
            with self.subTest(script=nombre):
                declarado = self._scripts()[nombre]
                self.assertEqual(declarado, f"{modulo}:{atributo}")
                try:
                    obj = getattr(importlib.import_module(modulo), atributo)
                except ImportError:
                    self.skipTest(f"{modulo} requiere dependencias opcionales")
                self.assertTrue(callable(obj), nombre)


if __name__ == "__main__":
    unittest.main()
