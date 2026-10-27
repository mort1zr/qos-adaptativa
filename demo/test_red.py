"""Comprueba el modo de espera con un Mininet falso, sin tocar interfaces."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class RedEnReposo(unittest.TestCase):
    def cargar(self):
        modulos = {n: types.ModuleType(n) for n in
                   ("mininet", "mininet.cli", "mininet.log", "mininet.net", "mininet.node")}
        modulos["mininet.cli"].CLI = Mock()
        for n in ("error", "info", "setLogLevel"):
            setattr(modulos["mininet.log"], n, Mock())
        modulos["mininet.net"].Mininet = Mock()
        for n in ("Node", "OVSSwitch", "RemoteController"):
            setattr(modulos["mininet.node"], n, object)
        ruta = Path(__file__).resolve().parents[1] / "topologia/empresa_xyz.py"
        spec = importlib.util.spec_from_file_location("topologia_demo_prueba", ruta)
        modulo = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modulos):
            spec.loader.exec_module(modulo)
        return modulo

    def test_esperar_no_abre_cli_y_limpia_al_terminar(self):
        m = self.cargar()
        with patch.object(m, "EmpresaXYZ") as empresa, patch.object(m.os, "geteuid", return_value=0), \
                patch.object(m, "controlador_activo", return_value=True), \
                patch.object(m.threading, "Event") as evento, patch.object(m.signal, "signal"), \
                patch("sys.argv", ["topologia", "--esperar", "--sin-cli"]):
            m.main()
        evento.return_value.wait.assert_called_once()
        m.CLI.assert_not_called()
        empresa.return_value.limpiar.assert_called_once()
        empresa.return_value.net.stop.assert_called_once()
        m.info.assert_any_call("*** Red lista\n")

    def test_fallo_durante_armado_limpia_recursos(self):
        m = self.cargar()
        with patch.object(m, "EmpresaXYZ") as empresa, patch.object(m.os, "geteuid", return_value=0), \
                patch.object(m, "controlador_activo", return_value=True), \
                patch.object(m.signal, "signal"), patch("sys.argv", ["topologia", "--esperar"]):
            empresa.return_value.construir.side_effect = KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                m.main()
        empresa.return_value.limpiar.assert_called_once()
        empresa.return_value.net.stop.assert_called_once()
