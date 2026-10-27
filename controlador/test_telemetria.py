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
from controlador.telemetria import (Telemetria, datos_panel, demanda, percentil, resumen_decisiones,
                                    serie_enlaces, uso_enlaces)
from politicas.cargador import cargar

INVENTARIO = """nombre,sede_id,sede,segmento,tipo,ip,gateway,detalle,area
ofcon1,0,Oficina central,administracion,pc_contabilidad,10.0.20.11,10.0.20.1,,Contabilidad
ofcon2,0,Oficina central,administracion,pc_contabilidad,10.0.20.12,10.0.20.1,,Contabilidad
ofpbx,0,Oficina central,servidores,central_telefonica,10.0.10.14,10.0.10.1,,Servidores
ofmon,0,Oficina central,administracion,pc_monitoreo,10.0.20.18,10.0.20.1,,Monitoreo
sa1nvr,1,Sala 1,cctv,nvr,10.1.40.10,10.1.40.1,,Cámaras
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

    def test_camaras_vistas_desde_la_oficina_en_ambos_extremos(self):
        # En la sala el otro extremo es la PC de monitoreo (no ofrece servicio):
        # el servicio sale del equipo local, el NVR (cctv).
        en_sala = self.tel.registrar_flujos(15, [muestra("10.1.40.10", "10.0.20.18", 2, 10_000, duracion=1)], ts=1)[0]
        self.assertEqual((en_sala["area"], en_sala["servicio"], en_sala["clase"]), ("Cámaras", "cctv", "vigilancia"))
        en_oficina = self.tel.registrar_flujos(5, [muestra("10.1.40.10", "10.0.20.18", 1, 10_000, duracion=1)], ts=1)[0]
        self.assertEqual((en_oficina["area"], en_oficina["servicio"], en_oficina["clase"]),
                         ("Monitoreo", "cctv", "vigilancia"))

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

    def test_bytes_no_disponibles_y_puerto_recreado(self):
        p = lambda b: [{"port_no": 2, "tx_bytes": b, "tx_packets": b // 1000, "tx_dropped": 0}]  # noqa: E731
        self.tel.registrar_puertos(15, p(1_000_000), ts=0)
        # Lectura "no disponible": no se guarda ni cambia la referencia.
        self.assertEqual(self.tel.registrar_puertos(15, p(2 ** 64 - 1), ts=5), [])
        self.assertAlmostEqual(self.tel.registrar_puertos(15, p(4_750_000), ts=10)[0]["mbps"], 3.0)
        # Red rearmada: el contador vuelve a empezar; esa lectura es solo referencia.
        self.assertEqual(self.tel.registrar_puertos(15, p(500_000), ts=15), [])
        self.assertAlmostEqual(self.tel.registrar_puertos(15, p(1_125_000), ts=20)[0]["mbps"], 1.0)
        self.assertLess(max(f["maximo_mbps"] for f in uso_enlaces(self.db, 10, ahora=21)), 31)

    def test_retencion_borra_el_detalle_pero_no_el_agregado(self):
        self.tel.registrar_flujos(5, [muestra("203.0.113.40", "10.0.20.11", 1, 1000, duracion=1)], ts=0)
        self.assertEqual(self.tel.limpiar(ts=25 * 3600), 1)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM flujos").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM areas").fetchone()[0], 1)

    def test_decisiones_y_su_tiempo(self):
        base = {"dpid": 15, "sede_id": 1, "sentido": "subida", "origen_ip": "10.1.20.13",
                "destino_ip": "10.0.10.14", "proto": 17, "origen": "sa1tel", "destino": "ofpbx",
                "area": "Telefonía", "clasificador": "politica", "motivo": "x"}
        decisiones = [dict(base, ts=10 + i, clase="tiempo_real", cola=1, ms=ms)
                      for i, ms in enumerate((1.0, 2.0, 3.0, 40.0))]
        decisiones.append(dict(base, ts=20, clase="masivo", cola=0, ms=0.5, clasificador="ninguno"))
        self.assertEqual(self.tel.registrar_decisiones(decisiones), 5)
        self.assertEqual(self.tel.registrar_decisiones([]), 0)
        r = {(f["clasificador"], f["clase"]): f for f in resumen_decisiones(self.db, 1, ahora=30)}
        tr = r[("politica", "tiempo_real")]
        self.assertEqual((tr["decisiones"], tr["cola"], tr["p50_ms"], tr["max_ms"]), (4, 1, 2.0, 40.0))
        self.assertEqual(r[("ninguno", "masivo")]["decisiones"], 1)
        # las decisiones identifican equipos: se borran con la retención
        self.assertEqual(self.tel.limpiar(ts=25 * 3600), 5)

    def test_base_del_sprint_anterior_se_actualiza(self):
        ruta = os.path.join(self.dir, "vieja.db")
        con = sqlite3.connect(ruta)
        con.execute("CREATE TABLE decisiones (ts REAL, dpid INTEGER, sede_id INTEGER, sentido TEXT, "
                    "origen_ip TEXT, destino_ip TEXT, proto INTEGER, origen TEXT, destino TEXT, area TEXT, "
                    "clasificador TEXT, clase TEXT, cola INTEGER, motivo TEXT, ms REAL)")
        con.execute("INSERT INTO decisiones VALUES (1,15,1,'subida','a','b',17,'a','b','x','politica',"
                    "'masivo',0,'m',0.5)")
        con.commit()
        con.close()
        tel = Telemetria(self.tel.inv, cargar(), ruta, intervalo_s=5)
        tel.registrar_decisiones([{"ts": 2, "clasificador": "destino", "clase": "critico", "cola": 2,
                                   "ms": 0.3, "servicio": "pagos", "via": "proactiva"}])
        tel.db.close()
        r = {f["clasificador"]: f for f in resumen_decisiones(ruta, 1, ahora=10)}
        self.assertEqual((r["politica"]["decisiones"], r["destino"]["proactivas"]), (1, 1))

    def test_percentil(self):
        self.assertIsNone(percentil([], 95))
        self.assertEqual(percentil([5, 1, 3], 50), 3)
        self.assertEqual(percentil(list(range(1, 101)), 95), 95)

    def test_datos_del_panel(self):
        # Sala 1: un teléfono (voz) y un cliente WiFi viendo streaming; Oficina: una descarga.
        for ts, k in ((100, 1), (105, 2)):
            self.tel.registrar_flujos(15, [muestra("10.1.20.13", "10.0.10.14", 2, 40_000 * k, duracion=5),
                                           muestra("203.0.113.30", "10.1.60.10", 1, 625_000 * k, duracion=5)],
                                      ts=ts)
            self.tel.registrar_flujos(5, [muestra("203.0.113.40", "10.0.20.11", 1, 1_250_000 * k, duracion=5)],
                                      ts=ts)
        self.tel.registrar_decisiones([{"ts": 101, "clasificador": "destino", "clase": "tiempo_real", "cola": 1,
                                        "ms": 0.8, "via": "proactiva"}])
        d = datos_panel(self.db, minutos=5, ahora=106)
        self.assertEqual(d["ahora"], 106)
        self.assertEqual([(a["area"], a["clase"]) for a in d["areas"]],
                         [("Contabilidad", "masivo"), ("WiFi clientes", "restringido"), ("Telefonía", "tiempo_real")])
        self.assertAlmostEqual(d["areas"][0]["mbps"], 2.0, places=2)
        self.assertEqual({(c["sede_id"], c["clase"]) for c in d["clases"]},
                         {(0, "masivo"), (1, "restringido"), (1, "tiempo_real")})
        self.assertEqual((d["decisiones"][0]["clase"], d["decisiones"][0]["proactivas"]), ("tiempo_real", 1))

    def test_panel_con_base_vacia(self):
        vacia = os.path.join(self.dir, "vacia.db")
        sqlite3.connect(vacia).close()
        d = datos_panel(vacia, minutos=5, ahora=10)
        self.assertEqual((d["enlaces"], d["clases"], d["areas"], d["decisiones"]), ([], [], [], []))
        self.assertEqual(serie_enlaces(vacia, 10, ahora=10), {})

    def test_serie_de_los_enlaces(self):
        p = lambda b1, b2: [{"port_no": 1, "tx_bytes": b1, "tx_packets": 0, "tx_dropped": 0},  # noqa: E731
                            {"port_no": 2, "tx_bytes": b2, "tx_packets": 0, "tx_dropped": 0}]
        for i, ts in enumerate((0, 5, 10)):
            self.tel.registrar_puertos(15, p(625_000 * i, 1_875_000 * i), ts=ts)
        s = serie_enlaces(self.db, minutos=10, ahora=11)
        self.assertEqual(list(s), ["1"])
        self.assertEqual(s["1"]["_capacidad"], 30)
        self.assertEqual(s["1"]["bajada"], [[5, 3.0], [10, 3.0]])
        self.assertEqual(s["1"]["subida"], [[5, 1.0], [10, 1.0]])
        self.assertEqual(serie_enlaces(self.db, minutos=0.05, ahora=11)["1"]["bajada"], [[10, 3.0]])

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
