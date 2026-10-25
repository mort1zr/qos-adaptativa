"""Pruebas de los clasificadores de flujos (PCIII-19). No necesitan Ryu, Mininet ni sudo.

  python3 -m unittest controlador.test_clasificadores -v
"""
import unittest

from controlador.clasificadores import (CLASIFICADORES, Clasificador, Decision, Flujo, PorPolitica,
                                        SinClasificar, armar_flujo, crear)
from politicas.cargador import cargar

EQUIPOS = [
    ("ofcms", 0, "servidores", "servidor_gestion", "10.0.10.10", "Servidores"),
    ("ofbak", 0, "servidores", "servidor_respaldo", "10.0.10.13", "Servidores"),
    ("ofpbx", 0, "servidores", "central_telefonica", "10.0.10.14", "Servidores"),
    ("ofcon1", 0, "administracion", "pc_contabilidad", "10.0.20.11", "Contabilidad"),
    ("ofsis1", 0, "administracion", "pc_sistemas", "10.0.20.13", "Sistemas"),
    ("ofmon", 0, "administracion", "pc_monitoreo", "10.0.20.18", "Monitoreo"),
    ("sa1srv", 1, "maquinas", "servidor_sala", "10.1.10.10", "Máquinas"),
    ("sa1caja", 1, "administracion", "pc_caja", "10.1.20.10", "Caja"),
    ("sa1musica", 1, "administracion", "pc_musica", "10.1.20.11", "Música"),
    ("sa1tel", 1, "administracion", "telefono_ip", "10.1.20.13", "Telefonía"),
    ("sa1sort", 1, "administracion", "pc_sorteos", "10.1.20.12", "Sorteos"),
    ("sa1pos1", 1, "pagos", "pos", "10.1.30.10", "Pagos"),
    ("sa1nvr", 1, "cctv", "nvr", "10.1.40.10", "Cámaras"),
    ("sa1cli1", 1, "wifi_clientes", "cliente_wifi", "10.1.60.10", "WiFi clientes"),
    ("inetvc", None, "internet", "videoconferencia", "203.0.113.10", "Internet"),
    ("inetia", None, "internet", "ia_generativa", "203.0.113.20", "Internet"),
    ("inetstr", None, "internet", "streaming", "203.0.113.30", "Internet"),
    ("inetupd", None, "internet", "descargas", "203.0.113.40", "Internet"),
    ("inetpago1", None, "internet", "pagos", "203.0.113.60", "Internet"),
]
ACC0 = {"nombre": "acc0", "sede_id": 0, "puerto_operador": 1, "puerto_sede": 2}
ACC1 = {"nombre": "acc1", "sede_id": 1, "puerto_operador": 1, "puerto_sede": 2}


class InventarioFalso:
    def __init__(self):
        self.por_nombre = {n: {"nombre": n, "sede_id": s, "segmento": seg, "tipo": t, "ip": ip, "area": a}
                           for n, s, seg, t, ip, a in EQUIPOS}
        self.por_ip = {e["ip"]: e for e in self.por_nombre.values()}

    def equipo(self, ip):
        return self.por_ip.get(ip)

    def ip(self, nombre):
        return self.por_nombre[nombre]["ip"]


class Clasificadores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pol = cargar()
        cls.inv = InventarioFalso()
        cls.politica = PorPolitica(cls.pol)

    def flujo(self, origen, destino, sw=ACC1, proto=17):
        """Flujo visto en el switch 'sw', entrando por el lado del origen."""
        o = self.inv.por_nombre[origen]
        in_port = sw["puerto_sede"] if o["sede_id"] == sw["sede_id"] else sw["puerto_operador"]
        return armar_flujo(self.inv, sw, self.inv.ip(origen), self.inv.ip(destino), proto, in_port, ts=1.0)

    def clase(self, origen, destino, sw=ACC1):
        return self.politica.clasificar(self.flujo(origen, destino, sw)).clase

    # ---------------- armar el flujo ----------------
    def test_flujo_sentido_y_extremos(self):
        sube = self.flujo("sa1tel", "ofpbx")
        self.assertEqual((sube.sentido, sube.local["nombre"], sube.remoto["nombre"]), ("subida", "sa1tel", "ofpbx"))
        baja = self.flujo("ofpbx", "sa1tel")
        self.assertEqual((baja.sentido, baja.local["nombre"], baja.remoto["nombre"]), ("bajada", "sa1tel", "ofpbx"))
        # el mismo flujo visto en el switch de la oficina: el equipo local es la central
        en_oficina = self.flujo("sa1tel", "ofpbx", sw=ACC0)
        self.assertEqual((en_oficina.sentido, en_oficina.local["nombre"]), ("bajada", "ofpbx"))

    def test_flujo_con_equipo_desconocido(self):
        f = armar_flujo(self.inv, ACC1, "198.51.100.7", "10.1.20.10", 6, 1, ts=1.0)
        self.assertEqual((f.local["nombre"], f.remoto), ("sa1caja", None))
        f = armar_flujo(self.inv, ACC1, "198.51.100.7", "198.51.100.8", 6, 1, ts=1.0)
        self.assertIsNone(f.local)
        self.assertEqual(self.politica.clasificar(f), Decision("masivo", "equipo fuera del inventario"))

    # ---------------- política ----------------
    def test_voz_en_ambos_sentidos_y_en_ambos_switches(self):
        for origen, destino in (("sa1tel", "ofpbx"), ("ofpbx", "sa1tel")):
            for sw in (ACC0, ACC1):
                self.assertEqual(self.clase(origen, destino, sw), "tiempo_real", (origen, destino, sw["nombre"]))

    def test_clases_del_casino(self):
        casos = {
            ("sa1caja", "inetvc"): "tiempo_real",      # videollamada desde la caja
            ("sa1srv", "ofcms"): "critico",            # reporte de máquinas
            ("sa1srv", "ofbak"): "masivo",             # respaldo del mismo servidor: NO crítico
            ("sa1pos1", "inetpago1"): "critico",       # pago con tarjeta
            ("sa1sort", "ofcms"): "critico",           # sorteo
            ("sa1musica", "inetstr"): "negocio",       # música de la sala (aunque sea streaming)
            ("sa1cli1", "inetstr"): "restringido",     # el mismo destino desde el WiFi de clientes
            ("sa1cli1", "inetvc"): "restringido",      # WiFi de clientes: restringido aunque sea video
            ("inetupd", "sa1caja"): "masivo",          # descarga
        }
        for (o, d), esperada in casos.items():
            self.assertEqual(self.clase(o, d), esperada, (o, d))

    def test_matriz_area_por_aplicacion(self):
        self.assertEqual(self.clase("ofsis1", "inetia", ACC0), "negocio")      # Sistemas
        self.assertEqual(self.clase("ofcon1", "inetia", ACC0), "masivo")       # Contabilidad

    def test_camaras_desde_la_oficina_en_ambos_extremos(self):
        self.assertEqual(self.clase("sa1nvr", "ofmon", ACC1), "vigilancia")
        self.assertEqual(self.clase("sa1nvr", "ofmon", ACC0), "vigilancia")

    def test_motivo_explica_la_decision(self):
        d = self.politica.clasificar(self.flujo("sa1cli1", "inetstr"))
        self.assertEqual(d.motivo, "WiFi de clientes siempre restringido")
        d = self.politica.clasificar(self.flujo("inetupd", "sa1caja"))
        self.assertEqual(d.motivo, "servicio 'descargas' por defecto")

    # ---------------- interfaz ----------------
    def test_sin_clasificar_todo_a_la_cola_por_defecto(self):
        d = SinClasificar(self.pol).clasificar(self.flujo("sa1tel", "ofpbx"))
        self.assertEqual(d.clase, "masivo")
        self.assertEqual(self.pol.cola(d.clase), 0)

    def test_crear_por_nombre(self):
        self.assertIsInstance(crear("politica", self.pol), PorPolitica)
        self.assertIsInstance(crear("ninguno", self.pol), SinClasificar)
        with self.assertRaises(ValueError):
            crear("tiktok", self.pol)

    def test_se_puede_enchufar_otro_clasificador(self):
        class Siempre(Clasificador):
            nombre = "siempre_critico"

            def clasificar(self, flujo: Flujo) -> Decision:
                return Decision("critico", "prueba")

        CLASIFICADORES[Siempre.nombre] = Siempre
        try:
            c = crear("siempre_critico", self.pol)
            self.assertEqual(self.pol.cola(c.clasificar(self.flujo("sa1cli1", "inetstr")).clase), 2)
        finally:
            del CLASIFICADORES[Siempre.nombre]


if __name__ == "__main__":
    unittest.main()
