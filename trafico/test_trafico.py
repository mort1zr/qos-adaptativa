"""Pruebas de los perfiles de tráfico y del generador (PCIII-17).

Ejecutar desde la raíz del proyecto (sin sudo ni Mininet):
  python3 -m unittest trafico.test_trafico -v
"""
import copy
import socket
import threading
import time
import unittest

from trafico import aplicaciones as ap
from trafico.generador import PUERTO_TCP, PUERTOS_UDP, Generador, PerfilInvalido, cargar_perfiles


def inventario():
    filas = [
        ("ofcms", 0, "servidores", "servidor_gestion", "10.0.10.10"),
        ("ofbak", 0, "servidores", "servidor_respaldo", "10.0.10.13"),
        ("ofpbx", 0, "servidores", "central_telefonica", "10.0.10.14"),
        ("ofger", 0, "administracion", "pc_gerencia", "10.0.20.10"),
        ("ofcon1", 0, "administracion", "pc_contabilidad", "10.0.20.11"),
        ("ofsis1", 0, "administracion", "pc_sistemas", "10.0.20.13"),
        ("ofsis2", 0, "administracion", "pc_sistemas", "10.0.20.14"),
        ("ofope", 0, "administracion", "pc_operaciones", "10.0.20.16"),
        ("ofmon", 0, "administracion", "pc_monitoreo", "10.0.20.18"),
        ("sa1srv", 1, "maquinas", "servidor_sala", "10.1.10.10"),
        ("sa1tm01", 1, "maquinas", "tragamonedas", "10.1.10.13"),
        ("sa1tm02", 1, "maquinas", "tragamonedas", "10.1.10.14"),
        ("sa1derby", 1, "maquinas", "derby", "10.1.10.11"),
        ("sa1caja", 1, "administracion", "pc_caja", "10.1.20.10"),
        ("sa1musica", 1, "administracion", "pc_musica", "10.1.20.11"),
        ("sa1tel", 1, "administracion", "telefono_ip", "10.1.20.13"),
        ("sa1sort", 1, "administracion", "pc_sorteos", "10.1.20.12"),
        ("sa1pos1", 1, "pagos", "pos", "10.1.30.10"),
        ("sa1pos2", 1, "pagos", "pos", "10.1.30.11"),
        ("sa1nvr", 1, "cctv", "nvr", "10.1.40.10"),
        ("sa1cli1", 1, "wifi_clientes", "cliente_wifi", "10.1.60.10"),
        ("sa1cli2", 1, "wifi_clientes", "cliente_wifi", "10.1.60.11"),
        ("sa1cli3", 1, "wifi_clientes", "cliente_wifi", "10.1.60.12"),
        ("sa1cli4", 1, "wifi_clientes", "cliente_wifi", "10.1.60.13"),
        ("inetvc", "inet", "internet", "videoconferencia", "203.0.113.10"),
        ("inetia", "inet", "internet", "ia_generativa", "203.0.113.20"),
        ("inetstr", "inet", "internet", "streaming", "203.0.113.30"),
        ("inetupd", "inet", "internet", "descargas", "203.0.113.40"),
        ("inetweb", "inet", "internet", "navegacion", "203.0.113.50"),
        ("inetpago1", "inet", "internet", "pagos", "203.0.113.60"),
        ("inetpago2", "inet", "internet", "pagos", "203.0.113.61"),
    ]
    return [{"nombre": n, "sede_id": s, "segmento": seg, "tipo": t, "ip": ip} for n, s, seg, t, ip in filas]


class Perfiles(unittest.TestCase):
    def setUp(self):
        self.gen = Generador(None, inventario(), semilla=7)

    def test_archivo_valido_y_completo(self):
        perfiles = cargar_perfiles()["perfiles"]
        self.assertGreaterEqual(len(perfiles), 10)
        for nombre in ("maquinas_reporte", "pagos_pos", "voip", "videollamada", "musica_sala",
                       "camara_remota", "ia_generativa", "descargas", "respaldo", "wifi_clientes"):
            self.assertIn(nombre, perfiles)

    def test_perfil_invalido(self):
        datos = copy.deepcopy(cargar_perfiles())
        datos["perfiles"]["voip"]["transporte"] = "sctp"
        import tempfile
        import yaml
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(datos, f)
        with self.assertRaises(PerfilInvalido):
            cargar_perfiles(f.name)

    def test_misma_semilla_mismo_plan(self):
        otro = Generador(None, inventario(), semilla=7)
        self.assertEqual(self.gen.plan("wifi_clientes", 1), otro.plan("wifi_clientes", 1))

    def test_distinta_semilla_distinto_plan(self):
        planes = {tuple(a["origen"] for a in Generador(None, inventario(), semilla=s).plan("wifi_clientes", 1))
                  for s in range(1, 8)}
        self.assertGreater(len(planes), 1)

    def test_el_puerto_no_delata_la_aplicacion(self):
        tcp, udp = set(), set()
        for perfil in self.gen.perfiles:
            for sede in (0, 1):
                for a in self.gen.plan(perfil, sede, intensidad=2):
                    (tcp if a["transporte"] == "tcp" else udp).add(a["puerto"])
        self.assertEqual(tcp, {PUERTO_TCP})                       # todo TCP por 443, como HTTPS
        self.assertTrue(all(PUERTOS_UDP[0] <= p <= PUERTOS_UDP[1] for p in udp))

    def test_sedes_de_cada_perfil(self):
        self.assertEqual(self.gen.plan("ia_generativa", 1), [])   # solo en la oficina
        self.assertEqual(len(self.gen.plan("ia_generativa", 0)), 2)
        self.assertEqual(self.gen.plan("pagos_pos", 0), [])       # solo en salas

    def test_intensidad_escala_cantidad_o_tasa(self):
        self.assertEqual(len(self.gen.plan("camara_remota", 1, intensidad=1)), 2)
        self.assertEqual(len(self.gen.plan("camara_remota", 1, intensidad=2)), 4)
        self.assertEqual(self.gen.plan("camara_remota", 1, intensidad=0), [])
        t1 = self.gen.plan("pagos_pos", 1, intensidad=1)[0]["tasa"]
        t3 = self.gen.plan("pagos_pos", 1, intensidad=3)[0]["tasa"]
        self.assertAlmostEqual(t3, 3 * t1, places=3)
        self.assertAlmostEqual(self.gen.plan("musica_sala", 1, intensidad=2)[0]["periodo"], 2.0)

    def test_reporte_de_maquinas_crece_con_las_maquinas(self):
        a = self.gen.plan("maquinas_reporte", 1)[0]
        self.assertEqual((a["origen"], a["destino"]), ("sa1srv", "ofcms"))
        self.assertAlmostEqual(a["tasa"], 0.5 * 3)               # 2 tragamonedas + derby

    def test_comandos_udp_con_vuelta(self):
        a = self.gen.plan("voip", 1)[0]
        cmds = self.gen.comandos(a, 30)
        equipos = [e for e, _ in cmds]
        self.assertEqual(sorted(equipos), ["ofpbx", "ofpbx", "sa1tel", "sa1tel"])   # 2 sumideros + 2 emisores
        self.assertEqual(sum(1 for _, argv in cmds if "sumidero" in argv), 2)

    def test_comando_pos_abre_una_conexion_por_pago(self):
        a = self.gen.plan("pagos_pos", 1)[0]
        argv = self.gen.comandos(a, 30)[0][1]
        self.assertIn("--nueva-conexion", argv)
        self.assertIn(a["destino"], ("inetpago1", "inetpago2"))

    def test_servidores_necesarios(self):
        self.assertEqual(set(self.gen.servidores_necesarios()),
                         {"ofcms", "ofbak", "inetia", "inetstr", "inetupd", "inetweb", "inetpago1", "inetpago2"})


def puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Aplicaciones(unittest.TestCase):
    """Las aplicaciones simuladas, de verdad, por la interfaz local."""

    @classmethod
    def setUpClass(cls):
        cls.puerto = puerto_libre()
        threading.Thread(target=ap.servidor, args=(cls.puerto, 30), daemon=True).start()
        time.sleep(0.3)

    def test_descarga_y_subida(self):
        self.assertGreater(ap.cliente("127.0.0.1", self.puerto, "descarga", 0.5), 0)
        self.assertGreater(ap.cliente("127.0.0.1", self.puerto, "subida", 0.5), 0)

    def test_transacciones_al_azar(self):
        n = ap.cliente("127.0.0.1", self.puerto, "transacciones", 2, peticion=500, respuesta=5000,
                       tasa=20, semilla=3)
        self.assertGreater(n, 15)
        self.assertLess(n, 70)

    def test_transacciones_periodicas_con_nueva_conexion(self):
        n = ap.cliente("127.0.0.1", self.puerto, "transacciones", 1.05, peticion=100, respuesta=100,
                       periodo=0.1, nueva_conexion=True, semilla=3)
        self.assertGreaterEqual(n, 9)

    def test_udp_y_sumidero(self):
        p = puerto_libre()
        resultado = {}
        t = threading.Thread(target=lambda: resultado.update(n=ap.sumidero(p, 2)))
        t.start()
        time.sleep(0.2)
        enviados = ap.udp("127.0.0.1", p, mbps=1.0, largo=1200, duracion=1, variacion=0.2, semilla=1)
        t.join()
        self.assertGreater(enviados, 90)                       # ~100 paquetes/s a 1 Mbps
        self.assertGreaterEqual(resultado["n"], enviados * 0.95)

    def test_tiempos_de_respuesta_en_json(self):
        import json
        import os
        import tempfile
        ruta = os.path.join(tempfile.mkdtemp(), "t.json")
        ap.cliente("127.0.0.1", self.puerto, "transacciones", 1.05, peticion=1500, respuesta=3000,
                   periodo=0.1, nueva_conexion=True, semilla=2, salida=ruta)
        with open(ruta) as f:
            r = json.load(f)
        self.assertGreaterEqual(r["transacciones"], 9)
        self.assertEqual(r["errores"], 0)
        self.assertLessEqual(r["p50_ms"], r["p95_ms"])

    def test_servidor_caido_cuenta_errores(self):
        import json
        import os
        import tempfile
        ruta = os.path.join(tempfile.mkdtemp(), "t.json")
        ap.cliente("127.0.0.1", puerto_libre(), "transacciones", 0.5, periodo=0.1,
                   nueva_conexion=True, salida=ruta)
        with open(ruta) as f:
            r = json.load(f)
        self.assertEqual(r["transacciones"], 0)
        self.assertGreater(r["errores"], 0)

    def test_variacion_reproducible(self):
        import random
        a = [ap.variar(random.Random(5), 1000, 0.3) for _ in range(3)]
        b = [ap.variar(random.Random(5), 1000, 0.3) for _ in range(3)]
        self.assertEqual(a, b)
        self.assertTrue(all(700 <= x <= 1300 for x in a))


if __name__ == "__main__":
    unittest.main()
