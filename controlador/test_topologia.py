"""Comprueba el mapa con inventarios pequeños."""
import tempfile
import unittest
from controlador.topologia import armar_topologia, leer_topologia, leer_progreso


class TopologiaTests(unittest.TestCase):
    def test_sedes_segmentos_islas_y_conectividad(self):
        equipos = [{"nombre": "maq", "ip": "10.1.1.1", "sede_id": 1, "sede": "Sala 1",
                    "segmento": "maquinas", "area": "Máquinas", "tipo": "tragamonedas"},
                   {"nombre": "inet", "ip": "203.0.113.10", "sede_id": None, "segmento": "internet",
                    "tipo": "videoconferencia"},
                   {"nombre": "of", "ip": "10.0.1.1", "sede_id": 0, "sede": "Oficina",
                    "segmento": "administracion", "area": "Sistemas", "tipo": "pc"}]
        sws = [{"nombre": "acc1", "tipo": "acceso", "sede_id": 1, "dpid": 15, "mbps": 30},
               {"nombre": "acc0", "tipo": "acceso", "sede_id": 0, "dpid": 5, "mbps": 50},
               {"nombre": "sw1maq", "tipo": "segmento", "sede_id": 1},
               {"nombre": "sw1is1", "tipo": "isla", "sede_id": 1}]
        d = armar_topologia(equipos, sws, ["acc1", "sw1is1"])
        self.assertEqual([s["id"] for s in d["sedes"]], [0, 1])
        sala = d["sedes"][1]
        self.assertTrue(sala["acceso"]["conectado"])
        self.assertEqual(sala["segmentos"][0]["equipos"], 1)
        self.assertEqual(sala["segmentos"][0]["areas"][0]["tipos"], {"tragamonedas": 1})
        self.assertEqual({s["nombre"] for s in sala["segmentos"][0]["switches"]}, {"sw1maq", "sw1is1"})
        self.assertEqual(d["resumen"], {"equipos": 3, "switches": 4, "conectados": 2})
        self.assertEqual(d["internet"][0]["servicio"], "videoconferencia")

    def test_archivos_inexistentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = leer_topologia(tmp + "/inventario.csv", tmp + "/switches.csv", [])
            self.assertEqual(d["sedes"], [])
            self.assertIn("Levanta", d["aviso"])
            self.assertEqual(leer_progreso(tmp), {"progreso": None, "reloj": None})
