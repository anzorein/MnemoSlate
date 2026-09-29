"""Tests de red (ping, espera de arranque, broadcast) y apagado remoto.

No tocan la red real: `subprocess.run` está mockeado y el `sleep` inyectado.
"""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mnemoslate.infra import net, power  # noqa: E402


def _proc(codigo: int, stderr: bytes = b"") -> mock.Mock:
    p = mock.Mock()
    p.returncode = codigo
    p.stdout = b""
    p.stderr = stderr
    return p


class TestPing(unittest.TestCase):
    def test_responde(self):
        with mock.patch.object(net.subprocess, "run", return_value=_proc(0)) as run:
            self.assertTrue(net.ping("192.0.2.15"))
        self.assertEqual(run.call_args[0][0][0], "ping")
        self.assertIn("192.0.2.15", run.call_args[0][0])

    def test_no_responde(self):
        with mock.patch.object(net.subprocess, "run", return_value=_proc(1)):
            self.assertFalse(net.ping("192.0.2.15"))

    def test_timeout_no_es_excepcion(self):
        with mock.patch.object(net.subprocess, "run", side_effect=subprocess.TimeoutExpired("ping", 4)):
            self.assertFalse(net.ping("192.0.2.15"))

    def test_sin_binario_ping(self):
        with mock.patch.object(net.subprocess, "run", side_effect=FileNotFoundError("ping")):
            self.assertFalse(net.ping("192.0.2.15"))

    def test_host_vacio(self):
        for vacio in ("", "   ", None):
            with self.subTest(vacio=vacio):
                self.assertFalse(net.ping(vacio))

    def test_flags_segun_os(self):
        with mock.patch.object(net, "os") as mock_os:
            mock_os.name = "nt"
            self.assertIn("-n", net._comando_ping("1.2.3.4", 2.0))
            mock_os.name = "posix"
            self.assertIn("-c", net._comando_ping("1.2.3.4", 2.0))


class TestEsperarActiva(unittest.TestCase):
    def test_responde_al_primer_intento(self):
        with mock.patch.object(net, "ping", return_value=True):
            self.assertTrue(net.esperar_activa("1.2.3.4", 120, dormir=lambda _: None))

    def test_responde_tras_varios_intentos(self):
        intentos = [False, False, True]
        esperas: list[float] = []
        with mock.patch.object(net, "ping", side_effect=intentos):
            ok = net.esperar_activa(
                "1.2.3.4", 120, intervalo=5, dormir=lambda s: esperas.append(s)
            )
        self.assertTrue(ok)
        self.assertEqual(esperas, [5, 5])  # durmió entre intentos, no después del último

    def test_agota_plazo_sin_responder(self):
        esperas: list[float] = []
        with mock.patch.object(net, "ping", return_value=False):
            ok = net.esperar_activa(
                "1.2.3.4", timeout=0, intervalo=5, dormir=lambda s: esperas.append(s)
            )
        self.assertFalse(ok)  # RF-2.3: la idea queda pendiente, no revienta

    def test_gancho_de_progreso(self):
        vistos: list[int] = []
        with mock.patch.object(net, "ping", side_effect=[False, True]):
            net.esperar_activa(
                "1.2.3.4", 120, dormir=lambda _: None, al_intentar=vistos.append
            )
        self.assertEqual(vistos, [1, 2])


class TestBroadcast(unittest.TestCase):
    def test_calcula_broadcast(self):
        self.assertEqual(net.broadcast_de("192.0.2.15", 24), "192.0.2.255")
        self.assertEqual(net.broadcast_de("192.168.1.50", 24), "192.168.1.255")
        self.assertEqual(net.broadcast_de("10.0.0.7", 8), "10.255.255.255")
        self.assertEqual(net.broadcast_de("192.0.2.15", 16), "192.0.255.255")
        self.assertEqual(net.broadcast_de("192.0.2.15", 32), "192.0.2.15")

    def test_ip_invalida(self):
        for mala in ("192.0.2", "192.0.2.999", "abc", "", "192.0.2.15.20"):
            with self.subTest(mala=mala):
                with self.assertRaises(ValueError):
                    net.broadcast_de(mala)

    def test_prefijo_invalido(self):
        with self.assertRaises(ValueError):
            net.broadcast_de("192.0.2.15", 33)


class TestPower(unittest.TestCase):
    def test_comando_ssh_shutdown(self):
        argv = power.comando_ssh("192.0.2.15", "usuario", "shutdown", retardo=5)
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)  # sin prompt de password
        self.assertIn("usuario@192.0.2.15", argv)
        self.assertEqual(argv[-1], "shutdown /s /t 5")

    def test_comando_ssh_con_llave(self):
        argv = power.comando_ssh("1.2.3.4", "u", "shutdown", llave="/home/pi/.ssh/id_ed25519")
        self.assertIn("-i", argv)
        self.assertIn("/home/pi/.ssh/id_ed25519", argv)

    def test_retardo_cero_rechazado(self):
        # /t 0 cortaría la sesión SSH antes de responder.
        with self.assertRaises(ValueError):
            power.comando_ssh("1.2.3.4", "u", "shutdown", retardo=0)

    def test_accion_invalida(self):
        with self.assertRaises(ValueError):
            power.comando_ssh("1.2.3.4", "u", "reboot-todo")

    def test_apagado_exitoso(self):
        with mock.patch.object(power.subprocess, "run", return_value=_proc(0)) as run:
            self.assertTrue(power.apagar_pc("1.2.3.4", "u"))
        self.assertEqual(run.call_args[0][0][0], "ssh")

    def test_cierre_por_apagado_se_trata_como_exito(self):
        # La PC se apaga y corta la sesión: igual hay que reportarlo como enviado.
        with mock.patch.object(
            power.subprocess, "run", return_value=_proc(255, b"kex_exchange_identification: Connection closed")
        ):
            self.assertTrue(power.apagar_pc("1.2.3.4", "u", retardo=5))

    def test_error_real_de_ssh(self):
        with mock.patch.object(
            power.subprocess, "run", return_value=_proc(255, b"Permission denied (publickey)")
        ):
            with self.assertRaises(power.ErrorApagado):
                power.apagar_pc("1.2.3.4", "u")

    def test_timeout_de_ssh(self):
        with mock.patch.object(power.subprocess, "run", side_effect=subprocess.TimeoutExpired("ssh", 20)):
            with self.assertRaises(power.ErrorApagado):
                power.apagar_pc("1.2.3.4", "u")

    def test_sin_cliente_ssh(self):
        with mock.patch.object(power.subprocess, "run", side_effect=FileNotFoundError("ssh")):
            with self.assertRaises(power.ErrorApagado):
                power.apagar_pc("1.2.3.4", "u")

    def test_suspend_no_usa_retardo(self):
        argv = power.comando_ssh("1.2.3.4", "u", "suspend", retardo=0)
        self.assertIn("SetSuspendState 0,1,0", argv[-1])  # 0 = suspender, no hibernar


if __name__ == "__main__":
    unittest.main()
