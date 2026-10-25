"""Pruebas de los escenarios y del reloj simulado (PCIII-18). Sin sudo ni Mininet.

  python3 -m unittest escenarios.test_escenarios -v
"""
import copy
import os
import tempfile
import unittest

import yaml

from escenarios.escenario import (ESCENARIOS, EscenarioInvalido, cargar_escenarios,
                                  plan_escenario)
from escenarios.reloj import RelojSimulado, leer_reloj


def base():
    with open(ESCENARIOS) as f:
        return yaml.safe_load(f)


def cargar_desde(datos):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(datos, f, allow_unicode=True)
    return cargar_escenarios(f.name)


class Escenarios(unittest.TestCase):
    def test_los_cinco_escenarios_validos(self):
        datos = cargar_escenarios()
        self.assertEqual(set(datos["escenarios"]),
                         {"apertura", "sorteo", "noche_alta", "respaldo_en_atencion", "madrugada"})

    def test_perfil_desconocido(self):
        d = base()
        d["escenarios"]["sorteo"]["fases"][0]["sala"]["tiktok"] = 1
        with self.assertRaises(EscenarioInvalido) as ctx:
            cargar_desde(d)
        self.assertIn("tiktok", str(ctx.exception))

    def test_dia_y_hora_invalidos(self):
        d = base()
        d["escenarios"]["sorteo"]["inicio"] = {"dia": "feriado", "hora": "25:00"}
        with self.assertRaises(EscenarioInvalido) as ctx:
            cargar_desde(d)
        self.assertIn("día", str(ctx.exception))
        self.assertIn("hora", str(ctx.exception))

    def test_intensidad_negativa_y_fase_muy_corta(self):
        d = base()
        d["escenarios"]["madrugada"]["fases"][0]["sala"]["respaldo"] = -1
        d["escenarios"]["madrugada"]["fases"][0]["duracion_s"] = 3
        with self.assertRaises(EscenarioInvalido) as ctx:
            cargar_desde(d)
        self.assertIn(">= 0", str(ctx.exception))
        self.assertIn("10 s", str(ctx.exception))

    def test_plan_sin_ruido_es_el_archivo(self):
        datos = cargar_escenarios()
        fases = plan_escenario(datos, "sorteo")
        self.assertEqual([f["nombre"] for f in fases], ["previa", "sorteo", "posterior"])
        self.assertEqual(fases[1]["sala"]["pagos_pos"], 4)
        self.assertEqual(fases[1]["oficina"], {})

    def test_ruido_reproducible_y_acotado(self):
        datos = cargar_escenarios()
        a = plan_escenario(datos, "noche_alta", semilla=7, ruido=0.1)
        b = plan_escenario(datos, "noche_alta", semilla=7, ruido=0.1)
        c = plan_escenario(datos, "noche_alta", semilla=8, ruido=0.1)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        wifi = a[0]["sala"]["wifi_clientes"]
        self.assertTrue(3.6 <= wifi <= 4.4 and wifi != 4)

    def test_escala_acorta_las_fases(self):
        datos = cargar_escenarios()
        self.assertEqual([f["duracion_s"] for f in plan_escenario(datos, "sorteo", escala=0.5)], [15, 30, 15])
        self.assertEqual(plan_escenario(datos, "sorteo", escala=0.01)[0]["duracion_s"], 10)  # mínimo 10 s

    def test_escenario_desconocido(self):
        with self.assertRaises(EscenarioInvalido):
            plan_escenario(cargar_escenarios(), "feriado")


class Reloj(unittest.TestCase):
    def test_tiempo_acelerado(self):
        r = RelojSimulado("lunes", "07:50", factor=12, inicio_real=1000.0)
        self.assertEqual(r.describir(1000.0), "lunes 07:50")
        self.assertEqual(r.describir(1050.0), "lunes 08:00")       # 50 s reales = 10 min
        self.assertEqual(r.describir(1000.0 + 600), "lunes 09:50")  # 10 min reales = 2 h

    def test_cambia_de_dia(self):
        r = RelojSimulado("sabado", "23:30", factor=12, inicio_real=0.0)
        self.assertEqual(r.describir(300.0), "domingo 00:30")
        self.assertEqual(r.simulado(0.0).date().isoformat(), "2026-11-07")

    def test_dia_con_tilde(self):
        self.assertEqual(RelojSimulado("miércoles", "15:00", inicio_real=0).describir(0), "miercoles 15:00")

    def test_guardar_y_leer(self):
        ruta = os.path.join(tempfile.mkdtemp(), "reloj.json")
        r = RelojSimulado("viernes", "21:00", factor=12, inicio_real=500.0)
        r.guardar("sorteo", "previa", ruta=ruta, estrategia="fila_corta")
        leido = leer_reloj(ruta)
        self.assertEqual(leido.describir(560.0), "viernes 21:12")

    def test_sin_reloj(self):
        self.assertIsNone(leer_reloj(os.path.join(tempfile.mkdtemp(), "no_existe.json")))


if __name__ == "__main__":
    unittest.main()
