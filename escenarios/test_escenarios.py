"""Pruebas de los escenarios y del reloj simulado (PCIII-18). Sin sudo ni Mininet.

  python3 -m unittest escenarios.test_escenarios -v
"""
import os
import tempfile
import unittest

import yaml

from escenarios.escenario import (ESCENARIOS, ESTRATEGIAS, EscenarioInvalido, cargar_escenarios,
                                  evaluar_udp, goodput_masivo, guardar_csv, metricas_telemetria,
                                  plan_escenario,
                                  poner_estrategia, sondas_de)
from escenarios.reloj import RelojSimulado, leer_reloj


def base():
    with open(ESCENARIOS) as f:
        return yaml.safe_load(f)


def cargar_desde(datos):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(datos, f, allow_unicode=True)
    return cargar_escenarios(f.name)


class Escenarios(unittest.TestCase):
    def test_los_diez_escenarios_validos(self):
        datos = cargar_escenarios()
        self.assertEqual(set(datos["escenarios"]),
                         {"apertura", "sorteo", "noche_alta", "respaldo_en_atencion", "madrugada",
                          "incidente_camaras", "sorteo_extraordinario", "respaldo_atrasado",
                          "evento_especial", "enlace_degradado"})

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


class Estrategias(unittest.TestCase):
    """Cada estrategia fija las colas de los enlaces Y el clasificador de Ryu (PCIII-19)."""

    class Colas:
        def __init__(self):
            self.hoja, self.llamadas = None, []

        def aplicar(self, puerto, mbps):
            self.llamadas.append(("colas", puerto))

        def linea_base(self, puerto, mbps):
            self.llamadas.append(("una_cola", puerto))

    class Emp:
        def __init__(self):
            self.colas = Estrategias.Colas()
            self.puertos_acceso = [("acc1", "acc1-eth1", 30, "subida"), ("acc1", "acc1-eth2", 30, "bajada")]

    class Api:
        class ErrorApi(RuntimeError):
            pass

        def __init__(self, falla=False):
            self.falla, self.pedidos = falla, []

        def poner_clasificador(self, nombre):
            if self.falla:
                raise self.ErrorApi("sin API")
            self.pedidos.append(nombre)

    def test_cada_estrategia_pide_su_clasificador(self):
        esperado = {"sin_qos": ("una_cola", "fifo", "ninguno"),
                    "fila_corta": ("colas", "pfifo:64", "ninguno"),
                    "prioridad": ("colas", "pfifo:64", "destino"),
                    "estatica": ("colas", "pfifo:64", "destino")}
        self.assertEqual(set(esperado), set(ESTRATEGIAS))
        for estrategia, (colas, hoja, clasificador) in esperado.items():
            emp, cliente = self.Emp(), self.Api()
            poner_estrategia(emp, estrategia, cliente=cliente)
            self.assertEqual({c for c, _ in emp.colas.llamadas}, {colas}, estrategia)
            self.assertEqual(emp.colas.hoja, hoja, estrategia)
            self.assertEqual(cliente.pedidos, [clasificador], estrategia)

    def test_sin_api_prioridad_falla_y_las_demas_avisan(self):
        avisos = []
        poner_estrategia(self.Emp(), "fila_corta", cliente=self.Api(falla=True), avisar=avisos.append)
        self.assertEqual(len(avisos), 1)
        with self.assertRaises(RuntimeError):
            poner_estrategia(self.Emp(), "prioridad", cliente=self.Api(falla=True))


class Metricas(unittest.TestCase):
    """Sondas y métricas del punto 7: video, web y lo que obtiene cada clase."""

    def test_sondas_generales_y_por_escenario(self):
        d = cargar_escenarios()
        self.assertEqual(set(sondas_de(d, "sorteo")), {"voz", "video", "pagos", "web"})
        self.assertEqual(set(sondas_de(d, "madrugada")), {"voz", "pagos"})       # sala cerrada
        self.assertEqual(d["objetivos"]["web_p95_ms"], 3000)

    def test_sonda_desconocida(self):
        d = base()
        d["escenarios"]["sorteo"]["sondas"] = {"netflix": True}
        with self.assertRaises(EscenarioInvalido) as ctx:
            cargar_desde(d)
        self.assertIn("netflix", str(ctx.exception))

    def test_ofrecido_por_clase_de_la_telemetria(self):
        import sqlite3
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE flujos (ts REAL, sede_id INTEGER, clase TEXT, servicio TEXT, bytes INTEGER)")
        filas = [(10, 1, "masivo", "respaldo", 75_000_000),       # 600 Mb en 60 s = 10 Mbps
                 (15, 1, "masivo", "descargas", 37_500_000),      # 5 Mbps
                 (15, 1, "tiempo_real", "voip", 750_000),         # 0.1 Mbps
                 (15, 2, "masivo", "respaldo", 99_999_999),       # otra sala: no cuenta
                 (99, 1, "masivo", "respaldo", 99_999_999)]       # fuera de la ventana
        con.executemany("INSERT INTO flujos VALUES (?,?,?,?,?)", filas)
        con.commit()
        con.close()
        r = metricas_telemetria(db, 1, 5, 60, 60)
        self.assertEqual((r["ofrecido_masivo_mbps"], r["ofrecido_tiempo_real_mbps"], r["ofrecido_restringido_mbps"]),
                         (15.0, 0.1, 0.0))
        self.assertEqual(metricas_telemetria(os.path.join(tempfile.mkdtemp(), "x", "no.db"), 1, 0, 1, 1), {})

    def test_goodput_del_respaldo(self):
        self.assertEqual(goodput_masivo({"respaldo": 10.0, "descargas": 5.0}),
                         {"respaldo_goodput_mbps": 10.0, "descargas_goodput_mbps": 5.0,
                          "respaldo_1gb_min": 13.3})                  # 8000 Mb / 10 Mbps = 800 s
        self.assertEqual(goodput_masivo({})["respaldo_1gb_min"], None)    # fase sin respaldo

    def test_video_se_evalua_por_el_peor_sentido_y_sin_mos(self):
        import json

        class M:
            OBJETIVOS = {"jitter_ms": 30, "perdida_pct": 1, "latencia_ms": 150, "mos": 4}

            @staticmethod
            def resultado_udp(ruta):
                with open(ruta) as f:
                    return json.load(f)

            @staticmethod
            def evaluar(f):
                return "sí" if f["perdida_pct"] <= 1 and f["mos"] is None else "no (pérdida)"

            @staticmethod
            def mos(*a):
                return 4.4

        d = tempfile.mkdtemp()
        rx = {}
        for sentido, perdida in (("subida", 0.0), ("bajada", 2.5)):
            ruta = os.path.join(d, sentido)
            with open(ruta, "w") as f:
                json.dump({"latencia_p95_ms": 12.0, "jitter_ms": 1.0, "perdida_pct": perdida}, f)
            rx[sentido] = (None, ruta)
        fila = evaluar_udp(M, rx, "video", con_mos=False)
        self.assertEqual((fila["video_perdida_pct"], fila["cumple_video"]), (2.5, "no (pérdida)"))
        self.assertNotIn("video_mos", fila)


class Operador_(unittest.TestCase):
    """Condiciones del enlace del operador (punto 2). Sin red: se anotan los comandos."""

    class Rop:
        """Router falso que imita a tc: 'replace' de netem CONSERVA el rate anterior
        (el comportamiento real que causó el error), 'del' + 'add' empieza de cero."""
        name = "rop"

        def __init__(self):
            self.comandos, self.qdisc = [], {}

        def cmd(self, texto):
            texto = texto.replace(" 2>&1", "").replace(" 2>/dev/null", "")
            self.comandos.append(texto)
            p = texto.split()
            if p[:3] == ["tc", "qdisc", "show"]:
                return self.qdisc.get(p[4], "")
            if p[:3] == ["tc", "qdisc", "del"]:
                self.qdisc.pop(p[4], None)
            if p[:3] in (["tc", "qdisc", "add"], ["tc", "qdisc", "replace"]) and "netem" in p:
                nuevo = " ".join(p[p.index("netem"):])
                viejo = self.qdisc.get(p[4], "")
                if p[2] == "replace" and " rate " in viejo and " rate " not in f" {nuevo} ":
                    nuevo += viejo[viejo.index(" rate "):]
                self.qdisc[p[4]] = "qdisc " + nuevo
            return ""

    def operador(self):
        from escenarios.operador import Operador
        rop = self.Rop()
        return rop, Operador(rop, retardos={1: 5, 4: 20}, capacidades={1: 30, 4: 10}, avisar=lambda t: None)

    def test_parametros_de_netem(self):
        from escenarios.operador import args_netem, condiciones
        self.assertEqual(args_netem(5, condiciones(None), 30), "delay 5ms")
        self.assertEqual(args_netem(0, condiciones(None), 30), "")
        # mitad de 30 Mbps con 250 ms de fila: 15e6 * 0.25 / 12000 = 312 paquetes
        self.assertEqual(args_netem(5, condiciones({"capacidad_pct": 50, "perdida_pct": 0.5}), 30),
                         "delay 5ms loss 0.5% rate 15mbit limit 312")

    def test_degradar_y_recuperar(self):
        rop, op = self.operador()
        op.aplicar(1, None)
        self.assertEqual(rop.comandos, [])                                   # ya estaba normal
        op.aplicar(1, {"capacidad_pct": 50, "perdida_pct": 0.5})
        self.assertIn("rate 15mbit limit 312", rop.qdisc["rop-s1"])          # bajada: antes de nuestras colas
        self.assertIn("ip link add ifb1 type ifb", rop.comandos)            # subida: después de nuestras colas
        self.assertIn("loss 0.5% rate 15mbit", rop.qdisc["ifb1"])
        n = len(rop.comandos)
        op.aplicar(1, {"capacidad_pct": 50, "perdida_pct": 0.5})
        self.assertEqual(len(rop.comandos), n)                               # sin cambios, nada que hacer
        op.aplicar(1, None)
        # El error de la primera versión: el enlace "recuperado" seguía limitado a 15 Mbps.
        self.assertEqual(rop.qdisc["rop-s1"], "qdisc netem delay 5ms")       # solo el retardo base
        self.assertNotIn("ifb1", rop.qdisc)                                  # subida sin límite
        self.assertEqual(sum("ip link add" in c for c in rop.comandos), 1)  # la IFB se crea una sola vez

    def test_si_tc_deja_el_limite_se_detecta(self):
        rop, op = self.operador()
        op.aplicar(1, {"capacidad_pct": 50})
        rop.cmd = lambda texto, original=rop.cmd: "" if " del " in texto else original(texto.replace(
            "tc qdisc add", "tc qdisc replace"))                             # un tc que no borra
        with self.assertRaises(RuntimeError):
            op.aplicar(1, None)

    def test_condiciones_invalidas_en_un_escenario(self):
        d = base()
        d["escenarios"]["enlace_degradado"]["fases"][1]["enlace"] = {"capacidad_pct": 0, "jitter_ms": 5}
        with self.assertRaises(EscenarioInvalido) as ctx:
            cargar_desde(d)
        self.assertIn("capacidad_pct", str(ctx.exception))
        self.assertIn("jitter_ms", str(ctx.exception))

    def test_la_fase_degradada_llega_al_plan(self):
        fases = plan_escenario(cargar_escenarios(), "enlace_degradado")
        self.assertEqual([f.get("enlace") for f in fases],
                         [None, {"capacidad_pct": 30, "perdida_pct": 0.5}, None])


class Csv(unittest.TestCase):
    def test_columnas_nuevas_no_corren_las_viejas(self):
        import csv
        ruta = os.path.join(tempfile.mkdtemp(), "r.csv")
        guardar_csv(ruta, [{"escenario": "sorteo", "voz": 10}])
        guardar_csv(ruta, [{"escenario": "sorteo", "voz": 11}])                    # mismas columnas: agrega
        guardar_csv(ruta, [{"escenario": "apertura", "franja": "cerrada->atencion", "voz": 12}])
        with open(ruta, newline="") as f:
            filas = list(csv.DictReader(f))
        self.assertEqual([f["voz"] for f in filas], ["10", "11", "12"])
        self.assertEqual([f["franja"] for f in filas], ["", "", "cerrada->atencion"])


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
