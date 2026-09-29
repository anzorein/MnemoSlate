"""Tests de Wake-on-LAN. No tocan la red: todo es parsing/armado de bytes."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mnemoslate.infra import wol  # noqa: E402

MAC = "11:22:33:44:55:66"
MAC_BYTES = bytes.fromhex("112233445566")


class TestNormalizarMac(unittest.TestCase):
    def test_formatos_aceptados(self):
        for texto in (
            "11:22:33:44:55:66",
            "11:22:33:44:55:66".lower(),
            "11-22-33-44-55-66",
            "11.22.33.44.55.66",
            "112233445566",
            "  11-22-33-44-55-66  ",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(wol.normalizar_mac(texto), MAC_BYTES)

    def test_mac_invalida(self):
        for malo in (
            "",
            "   ",
            "11:22:33:44:55",         # muy corta
            "11:22:33:44:55:66:99",   # muy larga
            "11:22:33:44:55:ZZ",      # hex inválido
            "11 22 33 44 55 66",      # separador no soportado
            "192.0.2.15",             # es una IP, no una MAC
            None,
        ):
            with self.subTest(malo=malo):
                with self.assertRaises(ValueError):
                    wol.normalizar_mac(malo)

    def test_formatear_mac(self):
        self.assertEqual(wol.formatear_mac("11-22-33-44-55-66"), MAC)
        self.assertEqual(wol.formatear_mac(MAC_BYTES), MAC)
        with self.assertRaises(ValueError):
            wol.formatear_mac(b"\x01\x02")


class TestMagicPacket(unittest.TestCase):
    def test_largo_y_sync(self):
        paquete = wol.build_magic_packet(MAC)
        self.assertEqual(len(paquete), 102)
        self.assertEqual(wol.TAMANO_PAQUETE, 102)
        self.assertEqual(paquete[:6], b"\xff" * 6)

    def test_mac_repetida_16_veces(self):
        paquete = wol.build_magic_packet(MAC)
        cuerpo = paquete[6:]
        self.assertEqual(len(cuerpo), 96)
        self.assertEqual(cuerpo, MAC_BYTES * 16)
        # Sin bytes de relleno: el paquete es exactamente sync + macs.
        self.assertEqual(set(paquete) - {0xFF} - set(MAC_BYTES), set())

    def test_mac_invalida_no_arma_paquete(self):
        with self.assertRaises(ValueError):
            wol.build_magic_packet("no-es-mac")


class TestEnvio(unittest.TestCase):
    def test_envia_102_bytes_por_udp(self):
        with mock.patch.object(wol.socket, "socket") as sock_cls:
            sock = sock_cls.return_value.__enter__.return_value
            sock.sendto.return_value = 102
            ok = wol.enviar_magic_packet(MAC, "192.0.2.255", 9)

        self.assertTrue(ok)
        sock.setsockopt.assert_called_once_with(
            wol.socket.SOL_SOCKET, wol.socket.SO_BROADCAST, 1
        )
        destino = sock.sendto.call_args[0][1]
        self.assertEqual(destino, ("192.0.2.255", 9))
        self.assertEqual(len(sock.sendto.call_args[0][0]), 102)

    def test_puerto_invalido(self):
        for puerto in (0, -1, 70000):
            with self.subTest(puerto=puerto):
                with self.assertRaises(ValueError):
                    wol.enviar_magic_packet(MAC, "192.0.2.255", puerto)

    def test_envio_parcial_reporta_false(self):
        with mock.patch.object(wol.socket, "socket") as sock_cls:
            sock = sock_cls.return_value.__enter__.return_value
            sock.sendto.return_value = 40  # solo 40 de 102
            self.assertFalse(wol.enviar_magic_packet(MAC, "192.0.2.255", 9))

    def test_enviar_multiples_recorre_canales(self):
        with mock.patch.object(wol.socket, "socket") as sock_cls:
            sock = sock_cls.return_value.__enter__.return_value
            sock.sendto.return_value = 102
            resultados = wol.enviar_multiples(MAC, ["192.0.2.255", "255.255.255.255"], (9, 7))

        self.assertEqual(len(resultados), 4)
        self.assertTrue(all(ok for _, _, ok in resultados))
        self.assertEqual(
            [(bc, p) for bc, p, _ in resultados],
            [
                ("192.0.2.255", 9),
                ("192.0.2.255", 7),
                ("255.255.255.255", 9),
                ("255.255.255.255", 7),
            ],
        )

    def test_enviar_multiples_tolera_oserror(self):
        with mock.patch.object(wol, "enviar_magic_packet", side_effect=OSError("sin red")):
            resultados = wol.enviar_multiples(MAC, ["192.0.2.255"], (9,))
        self.assertEqual(resultados, [("192.0.2.255", 9, False)])

    def test_enviar_multiples_valida_mac_antes_de_abrir_sockets(self):
        with mock.patch.object(wol, "enviar_magic_packet") as enviar:
            with self.assertRaises(ValueError):
                wol.enviar_multiples("basura", ["192.0.2.255"], (9,))
        enviar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
