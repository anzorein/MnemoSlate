"""Tests del sender Fase 4 (sin hardware: Entorno fake)."""
import os
import subprocess
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
    INSTRUCCION_CORTA,
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
    entorno_real,
    extraer_pensamiento,
    formatear_duracion,
    procesar_trabajo,
    ruta_payload_en_lore,
)

SCRIBE_OK = "title (X)\n# X ((X))\n\n## Resumen ((+Resumen))\n\ntexto.\n"
JSON_OK = '{"type":"x","text":"title (Y)"}\n{"nada":[1]}\n{"content":"cuerpo"}\n'
JSON_TRAZA = (
    '{"type":"step_start","sessionID":"ses_1",'
    ' "part":{"type":"step-start"}}\n'
    '{"type":"tool_use","sessionID":"ses_1",'
    ' "part":{"type":"tool","tool":"read","callID":"c1",'
    ' "state":{"status":"completed",'
    ' "input":{"filePath":"D:\\\\wiki\\\\04-society.md"},'
    ' "output":"' + "x" * 2000 + '"}}}\n'
    '{"type":"text","sessionID":"ses_1",'
    ' "part":{"type":"text","text":"EL DOCUMENTO FINAL"}}\n'
    '{"type":"step_finish","sessionID":"ses_1",'
    ' "part":{"reason":"stop","tokens":{"total":999}}}\n'
)


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

    def test_pensamiento_separa_traza_del_documento(self):
        doc = extraer_texto_salida(JSON_TRAZA)
        th = extraer_pensamiento(JSON_TRAZA, nota="trabajo #7 job 1")
        self.assertIn("EL DOCUMENTO FINAL", doc)
        # el documento NO se duplica en la traza
        self.assertNotIn("EL DOCUMENTO FINAL", th)
        self.assertIn("MnemoSlate-thoughts", th)
        self.assertIn("trabajo #7 job 1", th)
        self.assertIn("read", th)
        self.assertIn(r"D:\wiki\04-society.md", th)
        self.assertIn("stop", th)
        self.assertIn("999", th)
        # la salida de la herramienta (2000 x) va recortada, no entera
        self.assertIn("recortado", th)
        self.assertLess(len(th), len(JSON_TRAZA))

    def test_pensamiento_vacio_sin_traza(self):
        self.assertEqual(extraer_pensamiento("  texto plano  "), "")
        self.assertEqual(extraer_pensamiento(""), "")

    def test_sidecar_thoughts_por_job(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        conn = init_db(root / "t.db")
        try:
            a = crear_idea(conn, 1, "idea con traza")
            encolar_trabajo(conn, 1, [[a]])
            f = Fakes(salida=JSON_TRAZA)
            res = procesar_trabajo(conn, _infra(root), "tok", 1, f.entorno())
        finally:
            conn.close()
        self.assertTrue(res.ok)
        self.assertEqual(len(res.archivos), 2)
        principal = [p for p in res.archivos if "thoughts" not in p]
        lateral = [p for p in res.archivos if p.endswith("-thoughts.md")]
        self.assertEqual(len(principal), 1)
        self.assertEqual(len(lateral), 1)
        for p in res.archivos:
            self.assertTrue(Path(p).exists())
        th_txt = Path(lateral[0]).read_text(encoding="utf-8")
        self.assertIn("read", th_txt)
        doc_txt = Path(principal[0]).read_text(encoding="utf-8")
        self.assertIn("EL DOCUMENTO FINAL", doc_txt)
        self.assertNotIn("herramienta", doc_txt)
        tmp.cleanup()

    def test_comando_opencode(self):
        c = comando_opencode_remoto(r"D:\Documentos\Projects\Edessia", "p_1_1.json",
                                    modelo="a/b")
        self.assertIn("--format json", c)
        self.assertIn("-m a/b", c)
        self.assertIn('-f "p_1_1.json"', c)
        sin_modelo = comando_opencode_remoto(r"D:\Documentos\Projects\Edessia", "p.json")
        self.assertNotIn("-m", sin_modelo)

    def test_instruccion_pide_referencia_no_scribe(self):
        # scribe queda reservado para scribe/ -> PDF: la instrucción de producción
        # no debe pedirlo (evita la regresión de la Sesión 11).
        self.assertNotIn("scribe", INSTRUCCION_CORTA.lower())
        self.assertIn("referencia", INSTRUCCION_CORTA.lower())

    def test_instruccion_nombra_el_campo_prompt(self):
        # `-f` adjunta el JSON entero; el modelo tiene que saber que el encargo
        # está en el campo `prompt`.
        self.assertIn("prompt", INSTRUCCION_CORTA)

    def test_payload_vive_en_la_carpeta_del_lore(self):
        # Todo el payload vive bajo <EDESSIA_PC_DIR>: nada de home, nada de
        # variables de entorno del shell remoto (%VAR% solo lo expande cmd).
        r = ruta_payload_en_lore(r"D:\Documentos\Projects\Edessia",
                                 "mnemo_payload_1_1.json")
        self.assertEqual(r, r"D:\Documentos\Projects\Edessia\mnemo_payload_1_1.json")
        self.assertNotIn("%", r)
        con_barra = ruta_payload_en_lore(r"D:\Documentos\Projects\Edessia\\",
                                         "mnemo_payload_1_1.json")
        self.assertEqual(con_barra, r)

    def test_f_sin_variables_de_entorno(self):
        # Regresión: `-f` llevaba `%USERPROFILE%\...` y si el shell remoto de sshd
        # es PowerShell (no cmd) la variable viaja literal y el archivo no existe.
        c = comando_opencode_remoto(r"D:\Documentos\Projects\Edessia",
                                    "mnemo_payload_1_1.json")
        self.assertNotIn("%", c)
        self.assertIn('-f "mnemo_payload_1_1.json"', c)

    def test_mensaje_primero_y_f_ultimo(self):
        # Regresión: `-f` es un flag array (yargs) que se traga todo lo que sigue.
        # Con el mensaje después, opencode TOMABA sus palabras como rutas de archivo
        # y fallaba con "File not found: El".
        c = comando_opencode_remoto(r"D:\Documentos\Projects\Edessia", "p_1_1.json")
        self.assertLess(c.index(INSTRUCCION_CORTA), c.index("-f "),
                        "el mensaje debe ir antes de -f")
        self.assertLess(c.index(INSTRUCCION_CORTA), c.index("--format json"),
                        "el mensaje debe ir primero")
        self.assertTrue(c.rstrip().endswith('"'),
                        f"-f debe ser el ultimo token: {c}")

    def test_instruccion_sin_caracteres_hostiles_para_cmd(self):
        # cmd.exe trata estos como especiales: romperian el comando remoto.
        for ch in "()&|<>^%!\r\n":
            self.assertNotIn(ch, INSTRUCCION_CORTA, f"caracter hostil: {ch!r}")

    def test_stdin_cerrado_en_toda_llamada_ssh(self):
        # Regresión: por ssh el stdin remoto es una pipe que nunca cierra y
        # `opencode run` hace `await Bun.stdin.text()` con stdin no-TTY → cuelga
        # para siempre (opencode#38723). Todo subprocess por ssh va con DEVNULL.
        infra = InfraSettings(pc_mac="11:22:33:44:55:66", pc_ip="192.0.2.15",
                              ssh_user="u", ssh_key="k")
        llamadas = []

        class Proc:
            returncode = 0
            stdout = b'{"text":"hola"}'
            stderr = b""

        def fake_run(argv, **kw):
            llamadas.append((argv, kw))
            return Proc()

        with patch("mnemoslate.sender.subprocess.run", side_effect=fake_run):
            ent = entorno_real(infra, "", 0)
            ent.enviar_payload("{}", "p.json")
            ent.correr_opencode("p.json")
            ent.borrar_remoto("p.json")
        self.assertEqual(len(llamadas), 3)
        for argv, kw in llamadas:
            self.assertEqual(kw.get("stdin"), subprocess.DEVNULL,
                             f"falta stdin=DEVNULL en {argv}")

    def test_instruccion_no_rompe_el_comando_remoto(self):
        # El comando remoto entrecomilla la instrucción: unas comillas dobles
        # dentro romperían el cmd remoto.
        self.assertNotIn('"', INSTRUCCION_CORTA)
        self.assertIn(f'"{INSTRUCCION_CORTA}"',
                      comando_opencode_remoto(r"D:\Documentos\Projects\Edessia", "p.json"))

    def test_payload_ida_y_vuelta_en_la_carpeta_del_lore(self):
        # scp deposita y `del` limpia la MISMA ruta absoluta bajo el lore; `-f`
        # recibe el nombre pelado que resuelve contra el --dir. Sin shell, sin %.
        ed = r"D:\Documentos\Projects\Edessia"
        nombre = "mnemo_payload_7_2.json"
        remoto = ruta_payload_en_lore(ed, nombre)
        infra = InfraSettings(pc_mac="11:22:33:44:55:66", pc_ip="192.0.2.15",
                              ssh_user="u", ssh_key="k", edessia_pc_dir=ed)
        llamadas = []

        class Proc:
            returncode = 0
            stdout = b'{"text":"hola"}'
            stderr = b""

        def fake_run(argv, **kw):
            llamadas.append(argv)
            return Proc()

        with patch("mnemoslate.sender.subprocess.run", side_effect=fake_run):
            ent = entorno_real(infra, "", 0)
            ent.enviar_payload("{}", remoto)
            ent.correr_opencode(nombre)
            ent.borrar_remoto(remoto)
        scp, ssh_run, ssh_del = llamadas
        self.assertEqual(scp[0], "scp")
        self.assertTrue(scp[-1].endswith(remoto), scp)
        self.assertIn(f"--dir {ed}", ssh_run[-1])
        self.assertIn(f'-f "{nombre}"', ssh_run[-1])
        self.assertNotIn("%", ssh_run[-1])
        self.assertIn(f'del "{remoto}"', ssh_del[-1])

    def test_error_opencode_incluye_stdout(self):
        # Regresión: opencode escribe sus errores (ej: `File not found`) por
        # STDOUT via UI.error, no por stderr. El fallo llegaba mudo (`devolvió 1:`).
        ed = r"D:\Documentos\Projects\Edessia"
        infra = InfraSettings(pc_mac="11:22:33:44:55:66", pc_ip="192.0.2.15",
                              ssh_user="u", ssh_key="k", edessia_pc_dir=ed)

        class Proc:
            returncode = 1
            stdout = "File not found: mnemo_payload_1_1.json".encode()
            stderr = b""

        with patch("mnemoslate.sender.subprocess.run", return_value=Proc()):
            ent = entorno_real(infra, "", 0)
            with self.assertRaises(ErrorEnvio) as cm:
                ent.correr_opencode("mnemo_payload_1_1.json")
        self.assertIn("File not found", str(cm.exception))

    def test_comando_scp(self):
        c = comando_scp("1.2.3.4", "u", "k", "a.json", "b.json")
        self.assertEqual(c[0], "scp")
        self.assertIn("BatchMode=yes", c)

    def test_formatear_duracion(self):
        self.assertEqual(formatear_duracion(4.2), "4.2s")
        self.assertEqual(formatear_duracion(0), "0.0s")
        self.assertEqual(formatear_duracion(-3), "0.0s")
        self.assertEqual(formatear_duracion(83.4), "1m23s")
        self.assertEqual(formatear_duracion(3723), "1h02m")

    def test_mensaje_y_aviso_incluyen_tiempos(self):
        # El usuario pidió ver cuánto tardó cada paso (Telegram + stdout).
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        conn = init_db(root / "t.db")
        try:
            a = crear_idea(conn, 1, "idea con tiempos")
            encolar_trabajo(conn, 1, [[a]])
            f = Fakes()
            res = procesar_trabajo(conn, _infra(root), "tok", 1, f.entorno())
        finally:
            conn.close()
        self.assertTrue(res.ok)
        for marca in ("Tiempos", "ciclo PC", "envío payload (scp)",
                      "opencode run", "guardado en outputs", "Total",
                      "apagado PC (ssh)"):
            self.assertIn(marca, res.mensaje, marca)
        aviso_ok = next(m for m in f.avisos if "completado" in m)
        self.assertIn("Tiempos", aviso_ok)
        tmp.cleanup()

    def test_modo_test_mide_sin_apagado(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        conn = init_db(root / "t.db")
        try:
            a = crear_idea(conn, 1, "idea test")
            encolar_trabajo(conn, 1, [[a]])
            f = Fakes(encendida_por_mi=True)
            res = procesar_trabajo(conn, _infra(root), "tok", 1, f.entorno(),
                                   forzar_sin_apagar=True)
        finally:
            conn.close()
        self.assertTrue(res.ok)
        self.assertIn("modo test", res.mensaje)
        self.assertIn("Tiempos", res.mensaje)
        self.assertNotIn("apagado PC", res.mensaje)
        tmp.cleanup()

    def test_fallo_incluye_tiempo_transcurrido(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        conn = init_db(root / "t.db")
        try:
            a = crear_idea(conn, 1, "idea que falla")
            encolar_trabajo(conn, 1, [[a]])
            f = Fakes(opencode_ok=False)
            res = procesar_trabajo(conn, _infra(root), "tok", 1, f.entorno())
        finally:
            conn.close()
        self.assertFalse(res.ok)
        self.assertIn(" (en ", res.mensaje)
        tmp.cleanup()


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

    def test_test_usa_idea_configurable(self):
        # TEST_IDEA/TEST_TITULO pisan la canónica sin tocar código.
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        infra = _infra(root, test_idea="una taberna en el puerto bajo",
                       test_titulo="taberna-puerto")
        f = Fakes()
        rc = _probar_pipeline(infra, f.entorno())
        self.assertEqual(rc, SALIDA_OK)
        archivos = list((root / "outputs").glob("test-*.md"))
        self.assertEqual(len(archivos), 1)
        self.assertIn("taberna-puerto", archivos[0].name)
        payload, _ = f.salidas[0]
        self.assertIn("una taberna en el puerto bajo", payload)
        self.assertNotIn(IDEA_PRUEBA[:30], payload)
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
