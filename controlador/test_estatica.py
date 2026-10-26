"""Pruebas de la QoS estática por horario (PCIII-21). Sin sudo ni Mininet.

  python3 -m unittest controlador.test_estatica -v
"""
import datetime
import unittest

from controlador.estatica import Horario, HorarioInvalido, QoSEstatica, cargar_horario
from escenarios.reloj import RelojSimulado
from politicas.cargador import cargar


class Horario_(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pol = cargar()
        cls.h = cargar_horario(cls.pol)

    def test_franja_segun_la_hora_incluso_pasada_la_medianoche(self):
        casos = {"07:59": "cerrada", "08:00": "atencion", "15:00": "atencion", "23:59": "atencion",
                 "00:30": "atencion", "02:59": "atencion", "03:00": "cerrada", "05:00": "cerrada"}
        for hora, franja in casos.items():
            self.assertEqual(self.h.franja(hora)["nombre"], franja, hora)
        self.assertEqual(self.h.franja(datetime.time(4, 0))["nombre"], "cerrada")

    def test_techos_en_mbps_del_enlace(self):
        atencion, cerrada = self.h.franja("15:00"), self.h.franja("04:00")
        self.assertEqual(self.h.clases_controladas(), ["masivo"])
        self.assertEqual(self.h.techos(atencion, 30), {"masivo": 9_000_000})      # 30 % de 30 Mbps
        self.assertEqual(self.h.techos(cerrada, 30), {"masivo": 30_000_000})     # el de politicas.yaml
        self.assertEqual(self.h.techos(atencion, 10), {"masivo": 3_000_000})

    def invalido(self, franjas):
        with self.assertRaises(HorarioInvalido) as ctx:
            Horario({"franjas": franjas}, self.pol)
        return str(ctx.exception)

    def test_validaciones(self):
        self.assertIn("no cubren", self.invalido([{"nombre": "a", "desde": "08:00", "hasta": "20:00"}]))
        self.assertIn("se pisan", self.invalido([{"nombre": "a", "desde": "00:00", "hasta": "12:00"},
                                                 {"nombre": "b", "desde": "11:00", "hasta": "00:00"}]))
        texto = self.invalido([{"nombre": "a", "desde": "00:00", "hasta": "00:00",
                                "techos_pct": {"tiktok": 10, "masivo": 5, "restringido": 120}}])
        for parte in ("tiktok", "menor que su garantía", "entre 1 y 100"):
            self.assertIn(parte, texto)
        self.assertIn("HH:MM", self.invalido([{"nombre": "a", "desde": "25:00", "hasta": "08:00"}]))

    def test_una_franja_de_todo_el_dia(self):
        h = Horario({"franjas": [{"nombre": "siempre", "desde": "00:00", "hasta": "00:00"}]}, self.pol)
        self.assertEqual(h.franja("13:37")["nombre"], "siempre")


class GestorFalso:
    def __init__(self):
        self.llamadas = []

    def cambiar(self, puerto, clase, min_rate=None, max_rate=None):
        self.llamadas.append((puerto, clase, max_rate))


class Motor(unittest.TestCase):
    def test_aplica_solo_cuando_cambia_la_franja(self):
        reloj = RelojSimulado("lunes", "07:50", factor=12, inicio_real=1000.0)
        g = GestorFalso()
        avisos = []
        m = QoSEstatica(g, [("acc1-eth1", 30), ("acc1-eth2", 30), ("acc4-eth1", 10)], cargar_horario(),
                        leer_reloj=lambda: reloj, avisar=avisos.append)
        self.assertEqual(m.paso(1000.0), "cerrada")                       # 07:50
        self.assertEqual(g.llamadas, [("acc1-eth1", "masivo", 30_000_000), ("acc1-eth2", "masivo", 30_000_000),
                                      ("acc4-eth1", "masivo", 10_000_000)])
        g.llamadas.clear()
        self.assertEqual(m.paso(1040.0), "cerrada")                       # 07:58: nada que hacer
        self.assertEqual(g.llamadas, [])
        self.assertEqual(m.paso(1050.0), "atencion")                      # 08:00 en punto
        self.assertEqual(g.llamadas, [("acc1-eth1", "masivo", 9_000_000), ("acc1-eth2", "masivo", 9_000_000),
                                      ("acc4-eth1", "masivo", 3_000_000)])
        self.assertEqual([(c["de"], c["a"]) for c in m.cambios], [(None, "cerrada"), ("cerrada", "atencion")])
        self.assertEqual(len(avisos), 2)

    def test_dos_llamadas_a_la_vez_aplican_una_sola_vez(self):
        import threading
        import time

        class Lento(GestorFalso):
            def cambiar(self, *a, **k):
                time.sleep(0.05)              # como ovs-vsctl: tarda
                super().cambiar(*a, **k)

        reloj = RelojSimulado("martes", "04:00", factor=12, inicio_real=0.0)
        g = Lento()
        m = QoSEstatica(g, [("acc1-eth1", 30), ("acc1-eth2", 30)], cargar_horario(),
                        leer_reloj=lambda: reloj, avisar=lambda s: None)
        hilos = [threading.Thread(target=m.paso, args=(0.0,)) for _ in range(3)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(len(g.llamadas), 2)            # una por puerto, no 6
        self.assertEqual(len(m.cambios), 1)

    def test_sin_reloj_no_hace_nada(self):
        g = GestorFalso()
        m = QoSEstatica(g, [("acc1-eth1", 30)], cargar_horario(), leer_reloj=lambda: None, avisar=lambda s: None)
        self.assertIsNone(m.paso())
        self.assertEqual(g.llamadas, [])

    def test_no_mira_la_demanda(self):
        # La firma lo dice todo: el motor solo recibe el reloj; no hay telemetría que consultar.
        import inspect
        self.assertNotIn("telemetria", inspect.signature(QoSEstatica.__init__).parameters)


if __name__ == "__main__":
    unittest.main()
