"""Pruebas de la telemetría (PCIII-16). No necesitan Ryu, Mininet ni sudo.

Ejecutar desde la raíz del proyecto:
  python3 -m unittest controlador.test_telemetria -v
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from controlador.inventario import Inventario
from controlador.telemetria import Telemetria, demanda, uso_enlaces
from politicas.cargador import cargar

INVENTARIO = """nombre,sede_id,sede,segmento,tipo,ip,gateway,detalle,area
ofcon1,0,Oficina central,administracion,pc_contabilidad,10.0.20.11,10.0.20.1,,Contabilidad
ofcon2,0,Oficina central,administracion,pc_contabilidad,10.0.20.12,10.0.20.1,,Contabilidad
ofpbx,0,Oficina central,servidores,central_telefonica,10.0.10.14,10.0.10.1,,Servidores
sa1tel,1,Sala 1,administracion,telefono_ip,10.1.20.13,10.1.20.1,,Telefonía
sa1cli1,1,Sala 1,wifi_clientes,cliente_wifi,10.1.60.10,10.1.60.1,AP1,WiFi clientes
inetupd,inet,Internet,internet,descargas,203.0.113.40,203.0.113.1,,Internet
inetstr,inet,Internet,internet,streaming,203.0.113.30,203.0.113.1,,Internet
"""
SWITCHES = """nombre,dpid,tipo,sede_id,puerto_operador,puerto_sede,mbps
acc0,5,acceso,0,1,2,50
sw0adm,2,segmento,0,,,
acc1,15,acceso,1,1,2,30
"""


def muestra(origen, destino, in_port, bytes_, paquetes=None, proto=17, duracion=None):
    return {"origen_ip": origen, "destino_ip": destino, "proto": proto, "in_port": in_port,
            "bytes": bytes_, "paquetes": paquetes if paquetes is not None else bytes_ // 1000,
            "duracion_s": duracion}


class Telemetria_(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        inv, sws = os.path.join(self.dir, "inv.csv"), os.path.join(self.dir, "sw.csv")
        with open(inv, "w") as f:
            f.write(INVENTARIO)
        with open(sws, "w") as f:
            f.write(SWITCHES)
        self.db = os.path.join(self.dir, "t.db")
        self.tel = Telemetria(Inventario(inv, sws), cargar(), self.db, intervalo_s=5)

    def tearDown(self):
        self.tel.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_tasa_entre_dos_lecturas(self):
        f1 = self.tel.registrar_flujos(5, [muestra("203.0.113.40", "10.0.20.11", 1, 1_000_000, duracion=2)], ts=100)
        self.assertAlmostEqual(f1[0]["mbps"], 4.0)                      # 1 MB en 2 s
        f2 = self.tel.registrar_flujos(5, [muestra("203.0.113.40", "10.0.20.11", 1, 4_125_000)], ts=105)
        self.assertAlmostEqual(f2[0]["mbps"], 5.0)                      # 3.125 MB en 5 s

    def test_area_clase_y_sentido(self):
        f = self.tel.registrar_flujos(5, [muestra("203.0.113.40", "10.0.20.11", 1, 500_000, duracion=1)], ts=10)[0]
        self.assertEqual((f["area"], f["servicio"], f["clase"], f["sentido"]),
                         ("Contabilidad", "descargas", "masivo", "bajada"))
        self.assertEqual((f["origen"], f["destino"], f["local"]), ("inetupd", "ofcon1", "ofcon1"))

    def test_voz_entre_sedes_en_cada_extremo(self):
        en_sala = self.tel.registrar_flujos(15, [muestra("10.1.20.13", "10.0.10.14", 2, 8000, duracion=1)], ts=10)[0]
        self.assertEqual((en_sala["area"], en_sala["clase"], en_sala["sentido"]), ("Telefonía", "tiempo_real", "subida"))
        en_oficina = self.tel.registrar_flujos(5, [muestra("10.1.20.13", "10.0.10.14", 1, 8000, duracion=1)], ts=10)[0]
        self.assertEqual((en_oficina["area"], en_oficina["clase"], en_oficina["sentido"]),
                         ("Servidores", "tiempo_real", "bajada"))

    def test_wifi_de_clientes_restringido(self):
        f = self.tel.registrar_flujos(15, [muestra("203.0.113.30", "10.1.60.10", 1, 10_000, duracion=1)], ts=1)[0]
        self.assertEqual((f["area"], f["clase"]), ("WiFi clientes", "restringido"))

    def test_ip_desconocida(self):
        f = self.tel.registrar_flujos(5, [muestra("192.0.2.9", "198.51.100.7", 1, 10_000, duracion=1)], ts=1)[0]
        self.assertEqual((f["area"], f["clase"]), ("Desconocida", "masivo"))

    def test_switch_que_no_es_de_acceso_se_ignora(self):
        self.assertEqual(self.tel.registrar_flujos(2, [muestra("10.0.20.11", "10.0.20.12", 1, 999)], ts=1), [])

    def test_contador_reiniciado(self):
        m = lambda b: muestra("203.0.113.40", "10.0.20.11", 1, b, duracion=1)  # noqa: E731
        self.tel.registrar_flujos(5, [m(5_000_000)], ts=0)
        f = self.tel.registrar_flujos(5, [m(625_000)], ts=5)      # la regla se volvió a crear
        self.assertAlmostEqual(f[0]["mbps"], 5.0)                  # 625 kB en 1 s

    def test_flujo_vencido_guarda_sus_ultimos_bytes(self):
        m = lambda b: muestra("203.0.113.40", "10.0.20.11", 1, b, duracion=1)  # noqa: E731
        self.tel.registrar_flujos(5, [m(1_000_000)], ts=0)
        f = self.tel.registrar_flujos(5, [m(1_250_000)], ts=2, eliminados=True)
        self.assertEqual(f[0]["bytes"], 250_000)
        nuevo = self.tel.registrar_flujos(5, [m(100_000)], ts=10)  # el siguiente empieza de cero
        self.assertEqual(nuevo[0]["bytes"], 100_000)

    def test_agregado_por_area_y_consulta(self):
        # 2 PCs de Contabilidad descargando: 2 + 3 Mbps durante dos sondeos de 5 s.
        for ts, b1, b2 in ((100, 1_250_000, 1_875_000), (105, 2_500_000, 3_750_000)):
            self.tel.registrar_flujos(5, [muestra("203.0.113.40", "10.0.20.11", 1, b1, duracion=5),
                                          muestra("203.0.113.40", "10.0.20.12", 1, b2, duracion=5)], ts=ts)
        filas = demanda(self.db, minutos=10, area="contabilidad", ahora=106)
        self.assertEqual(len(filas), 1)
        self.assertEqual((filas[0]["area"], filas[0]["clase"], filas[0]["sentido"]),
                         ("Contabilidad", "masivo", "bajada"))
        self.assertAlmostEqual(filas[0]["promedio_mbps"], 5.0, places=2)
        self.assertAlmostEqual(filas[0]["maximo_mbps"], 5.0, places=2)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT flujos FROM areas LIMIT 1").fetchone()[0], 2)

    def test_promedio_cuenta_los_ratos_sin_trafico(self):
        m = lambda b: muestra("203.0.113.40", "10.0.20.11", 1, b, duracion=5)  # noqa: E731
        self.tel.registrar_flujos(5, [m(3_125_000)], ts=100)           # 5 Mbps
        self.tel.registrar_flujos(5, [], ts=105)                        # sondeo sin tráfico
        f = demanda(self.db, minutos=10, area="Contabilidad", ahora=106)[0]
        self.assertAlmostEqual(f["promedio_mbps"], 2.5, places=2)      # 5 Mbps la mitad del tiempo
        self.assertAlmostEqual(f["maximo_mbps"], 5.0, places=2)

    def test_por_clase(self):
        self.tel.registrar_flujos(15, [muestra("10.1.20.13", "10.0.10.14", 2, 40_000, duracion=5),
                                       muestra("203.0.113.30", "10.1.60.10", 1, 625_000, duracion=5)], ts=100)
        clases = {(f["clase"], f["sentido"]) for f in demanda(self.db, 10, por="clase", ahora=101)}
        self.assertEqual(clases, {("tiempo_real", "subida"), ("restringido", "bajada")})

    def test_uso_del_enlace_con_contadores_de_puertos(self):
        p = lambda b1, b2: [{"port_no": 1, "tx_bytes": b1, "tx_packets": 0, "tx_dropped": 0},  # noqa: E731
                            {"port_no": 2, "tx_bytes": b2, "tx_packets": 0, "tx_dropped": 3}]
        self.assertEqual(self.tel.registrar_puertos(15, p(0, 0), ts=0), [])   # solo referencia
        filas = self.tel.registrar_puertos(15, p(6_250_000, 18_750_000), ts=5)
        uso = {f["sentido"]: f["mbps"] for f in filas}
        self.assertAlmostEqual(uso["subida"], 10.0)     # sale hacia el operador
        self.assertAlmostEqual(uso["bajada"], 30.0)     # sale hacia la sede
        enl = {f["sentido"]: f for f in uso_enlaces(self.db, 10, ahora=6)}
        self.assertEqual(enl["bajada"]["uso_pct"], 100.0)

    def test_contador_no_disponible(self):
        # Si el switch no tiene el contador de descartes, OpenFlow manda 2^64 - 1.
        p = lambda b: [{"port_no": 1, "tx_bytes": b, "tx_packets": 0, "tx_dropped": 2 ** 64 - 1}]  # noqa: E731
        self.tel.registrar_puertos(15, p(0), ts=0)
        fila = self.tel.registrar_puertos(15, p(625_000), ts=5)[0]
        self.assertIsNone(fila["descartes"])
        self.assertAlmostEqual(fila["mbps"], 1.0)

    def test_retencion_borra_el_detalle_pero_no_el_agregado(self):
        self.tel.registrar_flujos(5, [muestra("203.0.113.40", "10.0.20.11", 1, 1000, duracion=1)], ts=0)
        self.assertEqual(self.tel.limpiar(ts=25 * 3600), 1)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM flujos").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM areas").fetchone()[0], 1)

    def test_inventario_se_recarga_si_cambia(self):
        inv = self.tel.inv
        self.assertFalse(inv.recargar())
        with open(inv.rutas[1], "a") as f:
            f.write("acc2,25,acceso,2,1,2,20\n")
        os.utime(inv.rutas[1], (1e9, 2e9))
        self.assertTrue(inv.recargar())
        self.assertTrue(inv.es_acceso(25))


if __name__ == "__main__":
    unittest.main()
