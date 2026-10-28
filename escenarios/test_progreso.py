"""Comprueba la publicación de fases sin levantar una red."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from escenarios.progreso import Progreso
from escenarios import escenario


class ProgresoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = Path(self.tmp.name) / "progreso.json"
        self.p = Progreso(self.ruta)
        self.p.iniciar({"escenarios": {"demo": {"descripcion": "Una prueba"}}},
                       {"demo": [{"nombre": "normal", "duracion_s": 15}]},
                       ["sin_qos", "prioridad"], {"sala": 1}, {})

    def test_fases_y_estrategias_ordenadas(self):
        d = json.loads(self.ruta.read_text())
        self.assertEqual([c["estrategia"] for c in d["corridas"]], ["sin_qos", "prioridad"])
        self.assertEqual(d["corridas"][0]["fases"][0]["estado"], "pendiente")
        self.assertFalse(self.ruta.with_suffix(".json.tmp").exists())

    def test_transiciones_y_metricas_sin_recalcular(self):
        self.p.empezar_fase("demo", "prioridad", "normal", "sábado 21:30")
        self.assertEqual(self.p.fase("demo", "prioridad", "normal")["estado"], "corriendo")
        fila = {"voz_lat95_ms": 11.2, "cumple_voz": "sí", "cumple_pagos": "no", "valida": "sí"}
        self.p.terminar_fase("demo", "prioridad", "normal", fila)
        fase = self.p.fase("demo", "prioridad", "normal")
        self.assertEqual(fase["metricas"], fila)
        self.assertEqual(fase["cumple"], {"voz": True, "pagos": False, "web": None})
        self.assertTrue(fase["valida"])
        self.assertEqual(fase["estado"], "terminada")
        self.assertEqual(self.p.fase("demo", "sin_qos", "normal")["estado"], "pendiente")

    def test_cpu_invalida_y_error(self):
        self.p.terminar_fase("demo", "prioridad", "normal", {"valida": "no (CPU 95 %)"})
        self.assertFalse(self.p.fase("demo", "prioridad", "normal")["valida"])
        self.p.finalizar("fallido", "No respondió la sonda")
        self.assertEqual(json.loads(self.ruta.read_text())["error"], "No respondió la sonda")

    def test_escritura_atomica_preserva_archivo_si_falla(self):
        original = self.ruta.read_bytes()
        with patch("escenarios.progreso.os.replace", side_effect=OSError("disco")):
            with self.assertRaises(OSError):
                self.p.finalizar()
        self.assertEqual(self.ruta.read_bytes(), original)
        self.assertFalse(Path(str(self.ruta) + ".tmp").exists())


class SalidasDemo(unittest.TestCase):
    def ejecutar(self, carpeta, argumentos):
        def falso(*args, **kwargs):
            kwargs["al_terminar"]([{"fase": "prueba", "voz_lat95_ms": 12}], [{"fase": "prueba"}])
        with patch.object(escenario, "ejecutar", side_effect=falso), \
                patch.object(escenario, "imprimir"), patch.object(escenario, "imprimir_objetivos"), \
                patch.object(escenario.os, "geteuid", return_value=0), \
                patch.object(escenario, "CSV", str(carpeta / "tesis.csv")), \
                patch.object(escenario, "CONTEXTO", str(carpeta / "contexto.csv")), \
                patch("sys.argv", ["escenario", "--nombre", "enlace_degradado"] + argumentos):
            escenario.main()

    def test_salida_separada_no_toca_tesis_ni_contexto_habitual(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "tesis.csv").write_text("original")
            (p / "contexto.csv").write_text("original")
            self.ejecutar(p, ["--salida", str(p / "demo.csv")])
            self.assertEqual((p / "tesis.csv").read_text(), "original")
            self.assertEqual((p / "contexto.csv").read_text(), "original")
            self.assertIn("voz_lat95_ms", (p / "demo.csv").read_text())
            self.assertTrue((p / "demo_contexto.csv").exists())
            self.assertFalse((p / "progreso.json").exists())

    def test_sin_argumentos_conserva_rutas_actuales(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self.ejecutar(p, [])
            self.assertTrue((p / "tesis.csv").exists())
            self.assertTrue((p / "contexto.csv").exists())
            self.assertFalse((p / "tesis_contexto.csv").exists())
