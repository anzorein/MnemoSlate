"""Tests del sender Fase 4 (sin hardware: Entorno fake)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mnemoslate.config import InfraSettings  # noqa: E402
from mnemoslate.db import (  # noqa: E402
    crear_idea,
    encolar_trabajo,
    init_db,
    listar_trabajos,
    obtener_idea,
    reclamar_trabajo,
)
from mnemoslate.lore import (  # noqa: E402
    build_referencia_prompt,
    build_scribe_prompt,
    envolver_referencia,
    envolver_scribe,
    render_scribe,
)
from mnemoslate.sender import (  # noqa: E402
    IDEA_PRUEBA,
    SALIDA_ERROR,
    SALIDA_OK,
    TITULO_PRUEBA,
    Entorno,
    ErrorEnvio,
    NoHayPC,
    _probar_pipeline,
    comando_opencode_remoto,
    comando_scp,
    ejecutar_cli,
    extraer_texto_salida,
    procesar_trabajo,
)

SCRIBE_OK = "title (X)\n# X ((X))\n\n## Resumen ((+Resumen))\n\ntexto.\n"
JSON_OK = '{"type":"x","text":"title (Y)"}\n{"nada":[1]}\n{"content":"cuerpo"}\n'


class Fakes:
    def __init__(self, salida=SCRIBE_OK, ciclo_ok=True, opencode_ok=True,
                 encendida_por_mi=True):
        self.salidas = []
        self.borrados = []
        self.apagados = 0
        self.avisos = []
        self._salida = salida
        self._ciclo_ok = ciclo_ok
        self._opencode_ok = opencode_ok
        self._encendida_por_mi = encendida_por_mi

    def asegurar_pc(self):
        if not self._ciclo_ok:
            raise NoHayPC("La PC no arrancó en 0s.")
        return self._encendida_por_mi

    def enviar_payload(self, contenido, remoto):
        self.salidas.append((contenido, remoto))

    def correr_opencode(self, remoto):
        if not self._opencode_ok:
            raise ErrorEnvio("ssh roto")
        return self._salida

    def borrar_remoto(self, remoto):
        self.borrados.append(remoto)

    def apagar(self):
        self.apagados += 1
        return True

    def notificar(self, texto):
        self.avisos.append(texto)

    def entorno(self):
        return Entorno(self.asegurar_pc, self.enviar_payload, self.correr_opencode,
                       self.borrar_remoto, self.apagar, self.notificar)


def _infra(root, **kw):
    base = dict(pc_mac="11:22:33:44:55:66", pc_ip="192.0.2.15",
                inbox_dir=str(root / "inbox"), outputs_dir=str(root / "outputs"))
    base.update(kw)
    return InfraSettings(**base)


class TestSender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = init_db(self.root / "t.db")
        self.a = crear_idea(self.conn, 1, "desierto que canta")
        self.b = crear_idea(self.conn, 1, "nomades del vidrio")
        self.infra = _infra(self.root)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_ciclo_feliz_lote(self):
        tid = encolar_trabajo(self.conn, 1, [[self.a], [self.b]], extra="x")
        f = Fakes()
        res = procesar_trabajo(self.conn, self.infra, "tok", 1, f.entorno())
        self.assertTrue(res.ok)
        self.assertEqual(len(res.archivos), 2)
        for a in res.archivos:
            self.assertTrue(Path(a).exists())
            self.assertEqual(Path(a).parent, self.root / "outputs")
        self.assertEqual(listar_trabajos(self.conn, "hecho")[0].id, tid)
        self.assertEqual(obtener_idea(self.conn, self.a).estado, "procesada")
        self.assertEqual(f.apagados, 1)
        self.assertTrue(any("✅" in m for m in f.avisos))
        self.assertEqual(len(f.borrados), 2)  # limpieza por job

    def test_ciclo_caido_no_apaga(self):
        tid = encolar_trabajo(self.conn, 1, [[self.a]])
        f = Fakes(ciclo_ok=False)
        res = procesar_trabajo(self.conn, self.infra, "tok", 1, f.entorno())
        self.assertFalse(res.ok)
        self.assertEqual(f.apagados, 0)
        self.assertEqual(listar_trabajos(self.conn, "encolado"), [])
        self.assertEqual(obtener_idea(self.conn, self.a).estado, "pendiente")
        self.assertTrue(any("siguen pendientes" in m for m in f.avisos))

    def test_opencode_falla_reencola(self):
        tid = encolar_trabajo(self.conn, 1, [[self.a]])
        f = Fakes(opencode_ok=False)
        res = procesar_trabajo(self.conn, self.infra, "tok", 1, f.entorno())
        self.assertFalse(res.ok)
        pendientes = listar_trabajos(self.conn, "encolado")
        self.assertEqual([t.id for t in pendientes], [tid])
        self.assertEqual(pendientes[0].intentos, 1)

    def test_opencode_agota_intentos(self):
        infra = _infra(self.root, max_intentos=1)
        tid = encolar_trabajo(self.conn, 1, [[self.a]])
        f = Fakes(opencode_ok=False)
        procesar_trabajo(self.conn, infra, "tok", 1, f.entorno())
        self.assertEqual([t.id for t in listar_trabajos(self.conn, "error")], [tid])

    def test_zombi_se_reclama(self):
        tid = encolar_trabajo(self.conn, 1, [[self.a]])
        t1 = reclamar_trabajo(self.conn)
        self.assertEqual(t1.id, tid)
        self.assertIsNone(reclamar_trabajo(self.conn))  # claim fresco: nadie más lo toma
        self.conn.execute("UPDATE trabajos SET claimed_at='2000-01-01T00:00:00.000Z'"
                          " WHERE id=?", (tid,))
        self.conn.commit()
        t2 = reclamar_trabajo(self.conn)
        self.assertIsNotNone(t2)
        self.assertEqual(t2.id, tid)

    def test_cola_vacia(self):
        f = Fakes()
        res = procesar_trabajo(self.conn, self.infra, "tok", 1, f.entorno())
        self.assertTrue(res.ok)
        self.assertIn("Nada encolado", res.mensaje)
        self.assertEqual(f.apagados, 0)

    def test_ya_encendida_no_apaga(self):
        encolar_trabajo(self.conn, 1, [[self.a]])
        f = Fakes(encendida_por_mi=False)
        res = procesar_trabajo(self.conn, self.infra, "tok", 1, f.entorno())
        self.assertTrue(res.ok)
        self.assertEqual(f.apagados, 0)
        self.assertIn("ya estaba encendida", res.mensaje)
        self.assertTrue(any("ya estaba encendida" in m for m in f.avisos))

    def test_flag_off_no_apaga(self):
        infra = _infra(self.root, apagar_al_finalizar=False)
        encolar_trabajo(self.conn, 1, [[self.a]])
        f = Fakes(encendida_por_mi=True)
        res = procesar_trabajo(self.conn, infra, "tok", 1, f.entorno())
        self.assertTrue(res.ok)
        self.assertEqual(f.apagados, 0)
        self.assertIn("APAGAR_AL_FINALIZAR=0", res.mensaje)

    def test_modo_test_no_apaga(self):
        encolar_trabajo(self.conn, 1, [[self.a]])
        f = Fakes(encendida_por_mi=True)
        res = procesar_trabajo(self.conn, self.infra, "tok", 1, f.entorno(),
                               forzar_sin_apagar=True)
        self.assertTrue(res.ok)
        self.assertEqual(f.apagados, 0)
        self.assertIn("modo test", res.mensaje)


class TestSalida(unittest.TestCase):
    def test_json_lines(self):
        txt = extraer_texto_salida(JSON_OK)
        self.assertIn("title (Y)", txt)
        self.assertIn("cuerpo", txt)

    def test_fallback_crudo(self):
        self.assertEqual(extraer_texto_salida("  texto plano  "), "texto plano")
        self.assertEqual(extraer_texto_salida(""), "")

    def test_comando_opencode(self):
        c = comando_opencode_remoto(r"D:\Docs\Edessia", "p_1_1.json", modelo="a/b")
        self.assertIn("--format json", c)
        self.assertIn("-m a/b", c)
        self.assertIn("-f", c)
        sin_modelo = comando_opencode_remoto(r"D:\Docs\Edessia", "p.json")
        self.assertNotIn("-m", sin_modelo)

    def test_comando_scp(self):
        c = comando_scp("1.2.3.4", "u", "k", "a.json", "b.json")
        self.assertEqual(c[0], "scp")
        self.assertIn("BatchMode=yes", c)


class TestScribe(unittest.TestCase):
    def test_render_sin_frontmatter(self):
        md = render_scribe([], extra="x", titulo="T")
        self.assertTrue(md.startswith("<!--"))
        self.assertIn("title (T)", md)
        self.assertIn("# T ((T))", md)
        self.assertIn("((+Resumen))", md)
        self.assertFalse(any(l.strip() == "---" for l in md.splitlines()))

    def test_envolver_trazabilidad(self):
        doc = envolver_scribe("title (Z)", [], extra="")
        self.assertIn("MnemoSlate | fuente:", doc)
        self.assertTrue(doc.endswith("title (Z)\n"))

    def test_prompt_con_guia(self):
        p = build_scribe_prompt([], extra="")
        self.assertIn("scribe.pf2.tools", p)
        self.assertIn("PROHIBIDO frontmatter", p)


class TestReferencia(unittest.TestCase):
    def test_prompt_referencia(self):
        p = build_referencia_prompt([], extra="hola")
        self.assertIn("REFERENCIA", p)
        self.assertIn("hola", p)

    def test_envolver_referencia_trazabilidad(self):
        doc = envolver_referencia("cuerpo", [], extra="x", nota="trabajo #7 job 1")
        self.assertTrue(doc.startswith("<!--"))
        self.assertIn("MnemoSlate | fuente:", doc)
        self.assertIn("trabajo #7 job 1", doc)
        self.assertTrue(doc.endswith("cuerpo\n"))


class TestCLI(unittest.TestCase):
    def _fakes_infra(self, root):
        return _infra(root), Fakes()

    def test_test_autocontenido_ok(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        infra, f = self._fakes_infra(root)
        rc = _probar_pipeline(infra, f.entorno())
        self.assertEqual(rc, SALIDA_OK)
        self.assertEqual(f.apagados, 0)  # --test jamás apaga la PC
        archivos = list((root / "outputs").glob("test-*.md"))
        self.assertEqual(len(archivos), 1)
        self.assertIn(TITULO_PRUEBA, archivos[0].name)
        payload, _ = f.salidas[0]
        self.assertIn(IDEA_PRUEBA[:30], payload)  # se usó la idea canónica
        tmp.cleanup()

    def test_ejecutar_cli_test_usa_db_temporal(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        db = root / "real.db"
        init_db(db).close()
        env = {"PC_MAC": "11:22:33:44:55:66", "PC_IP": "192.0.2.15",
               "OUTPUTS_DIR": str(root / "outputs")}
        f = Fakes()
        with patch.dict(os.environ, env, clear=True), \
                patch("mnemoslate.config.load_dotenv"):
            rc = ejecutar_cli("--test", db, entorno=f.entorno())
        self.assertEqual(rc, SALIDA_OK)
        conn = init_db(db)  # la DB real quedó intacta
        try:
            self.assertEqual(listar_trabajos(conn), [])
            self.assertIsNone(obtener_idea(conn, 1))
        finally:
            conn.close()
        tmp.cleanup()

    def test_sin_config_error(self):
        # Limpiar os.environ NO alcanza: en la Pi hay un .env real en la raíz del
        # repo y `_buscar_env()` lo carga igual (config.py), con lo que la config
        # "faltante" en realidad existe. Se anula load_dotenv para aislar el test.
        tmp = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {}, clear=True), \
                patch("mnemoslate.config.load_dotenv"):
            rc = ejecutar_cli("--test", Path(tmp.name) / "t.db")
        self.assertEqual(rc, SALIDA_ERROR)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
