"""Pruebas del gestor de colas HTB (PCIII-14).

Ejecutar desde la raíz del proyecto (no hace falta sudo ni Mininet):
  python3 -m unittest controlador.test_colas -v

Las pruebas levantan una base de datos de Open vSwitch propia y temporal
(ovsdb-server), sin tocar la de la máquina. Si Open vSwitch no está
instalado, esas pruebas se omiten.
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest

from controlador.colas import (BURST_MIN_BITS, ErrorColas, GestorColas, _ejecutar, _mapa,
                               comando_raiz, comandos_hoja, validar_hoja)


def sin_tc(cmd):
    """Ejecuta ovs-vsctl de verdad pero no tc: los puertos de prueba no existen en Linux."""
    return "" if cmd[0] == "tc" else _ejecutar(cmd)
from politicas.cargador import cargar

HAY_OVS = all(shutil.which(b) for b in ("ovsdb-server", "ovsdb-tool", "ovs-vsctl"))
ESQUEMAS = ["/usr/share/openvswitch/vswitch.ovsschema",
            "/usr/local/share/openvswitch/vswitch.ovsschema"]


class Plan(unittest.TestCase):
    """Cálculo de las colas, sin Open vSwitch."""

    def setUp(self):
        self.g = GestorColas(cargar(), ejecutar=lambda cmd: "")

    def test_una_cola_por_clase(self):
        plan = self.g.plan(30)
        self.assertEqual([q["cola"] for q in plan], [0, 1, 2, 3, 4, 5])
        self.assertEqual(plan[0]["clase"], "masivo")

    def test_tasas_para_30_mbps(self):
        tr = next(q for q in self.g.plan(30) if q["clase"] == "tiempo_real")
        self.assertEqual((tr["min_rate"], tr["max_rate"], tr["prioridad"]),
                         (4_500_000, 12_000_000, 0))

    def test_burst_por_defecto_20_ms(self):
        self.assertEqual(self.g.plan(30)[0]["burst"], 600_000)   # 20 ms de 30 Mbps, en bits

    def test_burst_0_lo_decide_ovs(self):
        g = GestorColas(cargar(), burst_ms=0, ejecutar=lambda cmd: "")
        self.assertTrue(all(q["burst"] is None for q in g.plan(30)))

    def test_burst_en_ms_del_techo(self):
        g = GestorColas(cargar(), burst_ms=10, ejecutar=lambda cmd: "")
        masivo = g.plan(30)[0]
        self.assertEqual(masivo["burst"], 300_000)          # 10 ms de 30 Mbps
        restringido = next(q for q in g.plan(1) if q["clase"] == "restringido")
        self.assertEqual(restringido["burst"], BURST_MIN_BITS)  # nunca menos de un paquete

    def test_fila_de_espera_por_cola(self):
        self.assertEqual(comandos_hoja("acc1-eth2", 0, "fifo"),
                         ["tc", "qdisc", "del", "dev", "acc1-eth2", "parent", "1:1"])
        self.assertEqual(comandos_hoja("acc1-eth2", 0, "pfifo:64"),
                         ["tc", "qdisc", "replace", "dev", "acc1-eth2", "parent", "1:1",
                          "handle", "10:", "pfifo", "limit", "64"])
        self.assertEqual(comandos_hoja("acc1-eth2", 5, "fq_codel")[-3:], ["handle", "60:", "fq_codel"])

    def test_fila_de_espera_invalida(self):
        for mala in ("pfifo", "pfifo:1", "codel"):
            with self.assertRaises(ErrorColas):
                validar_hoja(mala)

    def test_aplicar_pone_la_fila_en_cada_cola(self):
        comandos = []
        g = GestorColas(cargar(), hoja="fq_codel",
                        ejecutar=lambda cmd: comandos.append(cmd) or ("[]" if "get" in cmd else ""))
        g.aplicar("acc1-eth2", 30)
        tc = [c for c in comandos if c[0] == "tc"]
        self.assertEqual(len(tc), 6)
        self.assertEqual({c[6] for c in tc}, {"1:1", "1:2", "1:3", "1:4", "1:5", "1:6"})

    def test_raiz_en_bytes(self):
        self.assertEqual(comando_raiz("acc1-eth2", 30_000_000, 20)[-4:],
                         ["burst", "75000", "cburst", "75000"])

    def test_reforzar_raiz_en_todos_los_puertos_con_htb(self):
        comandos = []

        def ejecutar(cmd):
            comandos.append(cmd)
            if "find" in cmd:
                return "acc1-eth1,q1\nacc1-eth2,q2\nacc9-eth1,q9"
            if "list" in cmd:
                return ("q1,linux-htb,max-rate=30000000\nq2,linux-htb,max-rate=20000000\n"
                        "q9,linux-noop,")
            return ""
        g = GestorColas(cargar(), ejecutar=ejecutar)
        self.assertEqual(g.reforzar_raiz(), ["acc1-eth1", "acc1-eth2"])
        tc = [c for c in comandos if c[0] == "tc"]
        self.assertEqual([c[4] for c in tc], ["acc1-eth1", "acc1-eth2"])
        self.assertIn("50000", tc[1])                      # 20 ms de 20 Mbps

    def test_leer_rafaga_raiz(self):
        for salida, esperado in (("class htb 1:fffe root rate 30Mbit ceil 30Mbit burst 1500b cburst 1500b", 1500),
                                 ("class htb 1:fffe root rate 30Mbit ceil 30Mbit burst 73250b cburst 73250b", 73250),
                                 ("class htb 1:fffe root rate 1Gbit ceil 1Gbit burst 2Mb cburst 2Mb", 2 * 1024 * 1024)):
            g = GestorColas(cargar(), ejecutar=lambda cmd, s=salida: s)
            self.assertEqual(g.rafaga_raiz("x"), esperado)

    def test_contadores_por_cola(self):
        salida = ("class htb 1:fffe root rate 30Mbit ceil 30Mbit burst 75000b cburst 75000b \n"
                  " Sent 900000 bytes 700 pkt (dropped 0, overlimits 0 requeues 0) \n"
                  " backlog 0b 0p requeues 0\n"
                  "class htb 1:1 parent 1:fffe leaf 10: prio 4 rate 3Mbit ceil 30Mbit burst 75000b \n"
                  " Sent 600000 bytes 450 pkt (dropped 12, overlimits 30 requeues 0) \n"
                  "class htb 1:2 parent 1:fffe leaf 20: prio 0 rate 4500Kbit ceil 12Mbit burst 29999b \n"
                  " Sent 8000 bytes 50 pkt (dropped 0, overlimits 0 requeues 0) \n"
                  "class htb 1:b parent 1:fffe prio 7 rate 1Mbit ceil 1Mbit burst 1600b \n"
                  " Sent 0 bytes 0 pkt (dropped 0, overlimits 0 requeues 0) \n")
        g = GestorColas(cargar(), ejecutar=lambda cmd: salida)
        c = g.contadores_colas("acc1-eth2")
        self.assertEqual(sorted(c), [0, 1, 10])                   # 1:b (hex) = cola 10; sin la raíz
        self.assertEqual(c[0], {"bytes": 600000, "paquetes": 450, "descartes": 12})
        self.assertEqual(c[1]["bytes"], 8000)

    def test_mapa_de_ovs_vsctl(self):
        self.assertEqual(_mapa('{burst="240000", min-rate="1"}'), {"burst": "240000", "min-rate": "1"})
        self.assertEqual(_mapa("{0=aaa, 1=bbb}"), {"0": "aaa", "1": "bbb"})
        self.assertEqual(_mapa("{}"), {})


@unittest.skipUnless(HAY_OVS, "Open vSwitch no está instalado")
class ConOVSDB(unittest.TestCase):
    """Comandos reales de ovs-vsctl contra una base de datos temporal."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="ovsdb-")
        esquema = next((e for e in ESQUEMAS if os.path.exists(e)), None)
        if not esquema:
            raise unittest.SkipTest("no se encontró vswitch.ovsschema")
        db, sock = os.path.join(cls.dir, "conf.db"), os.path.join(cls.dir, "db.sock")
        subprocess.run(["ovsdb-tool", "create", db, esquema], check=True)
        subprocess.run(["ovsdb-server", db, f"--remote=punix:{sock}",
                        f"--unixctl={os.path.join(cls.dir, 'ctl')}",
                        f"--pidfile={os.path.join(cls.dir, 'pid')}",
                        f"--log-file={os.path.join(cls.dir, 'log')}", "--detach"], check=True)
        for _ in range(50):
            if os.path.exists(sock):
                break
            time.sleep(0.1)
        cls.db = f"unix:{sock}"
        cls.g = GestorColas(cargar(), db=cls.db, esperar=False, ejecutar=sin_tc)
        cls.g.vsctl("init")
        cls.g.vsctl("add-br", "acc1", "--", "add-port", "acc1", "acc1-eth1",
                    "--", "add-port", "acc1", "acc1-eth2")

    @classmethod
    def tearDownClass(cls):
        with open(os.path.join(cls.dir, "pid")) as f:
            os.kill(int(f.read().strip()), 15)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def tearDown(self):
        self.g.quitar("acc1-eth1")
        self.g.quitar("acc1-eth2")

    def filas(self, tabla):
        return self.g.vsctl("--columns=_uuid", "list", tabla).count("_uuid")

    def test_aplicar_crea_seis_colas(self):
        self.g.aplicar("acc1-eth1", 30)
        e = self.g.leer("acc1-eth1")
        self.assertEqual(e["max_rate"], 30_000_000)
        self.assertEqual(sorted(e["colas"]), [0, 1, 2, 3, 4, 5])
        self.assertEqual(e["colas"][1]["min_rate"], 4_500_000)   # tiempo_real 15 %
        self.assertEqual(e["colas"][1]["max_rate"], 12_000_000)  # techo 40 %
        self.assertEqual(e["colas"][5]["prioridad"], 5)          # restringido

    def test_reaplicar_no_deja_filas_huerfanas(self):
        self.g.aplicar("acc1-eth1", 30)
        self.g.aplicar("acc1-eth1", 20)
        self.g.linea_base("acc1-eth1", 20)
        self.assertEqual(self.filas("qos"), 1)
        self.assertEqual(self.filas("queue"), 1)
        self.assertEqual(self.g.leer("acc1-eth1")["colas"][0]["max_rate"], 20_000_000)

    def test_quitar_borra_todo(self):
        self.g.aplicar("acc1-eth1", 30)
        self.g.quitar("acc1-eth1")
        self.assertIsNone(self.g.leer("acc1-eth1"))
        self.assertEqual(self.filas("qos") + self.filas("queue"), 0)

    def test_cambiar_en_caliente_mantiene_la_cola(self):
        self.g.aplicar("acc1-eth1", 30)
        antes = self.g.leer("acc1-eth1")["colas"][0]["uuid"]
        self.g.cambiar("acc1-eth1", "masivo", max_rate=10_000_000)
        q = self.g.leer("acc1-eth1")["colas"][0]
        self.assertEqual(q["uuid"], antes)        # misma fila: no se rehízo nada
        self.assertEqual(q["max_rate"], 10_000_000)
        self.assertEqual(q["min_rate"], 3_000_000)  # la garantía no cambió

    def test_cambiar_rechaza_valores_imposibles(self):
        self.g.aplicar("acc1-eth1", 30)
        with self.assertRaises(ErrorColas):
            self.g.cambiar("acc1-eth1", "masivo", max_rate=40_000_000)   # más que el enlace
        with self.assertRaises(ErrorColas):
            self.g.cambiar("acc1-eth1", "masivo", min_rate=20_000_000)   # garantías suman más que el enlace
        with self.assertRaises(ErrorColas):
            self.g.cambiar("acc1-eth1", "tiempo_real", max_rate=1_000_000)  # techo < garantía

    def test_cambiar_sin_colas_avisa(self):
        self.g.linea_base("acc1-eth2", 30)
        with self.assertRaises(ErrorColas):
            self.g.cambiar("acc1-eth2", "tiempo_real", max_rate=5_000_000)

    def test_cada_puerto_tiene_sus_colas(self):
        self.g.aplicar("acc1-eth1", 30)
        self.g.aplicar("acc1-eth2", 30)
        self.g.cambiar("acc1-eth1", "masivo", max_rate=10_000_000)
        self.assertEqual(self.g.leer("acc1-eth2")["colas"][0]["max_rate"], 30_000_000)

    def test_reforzar_raiz_encuentra_los_puertos(self):
        self.g.aplicar("acc1-eth1", 30)
        self.g.linea_base("acc1-eth2", 20)
        self.assertEqual(sorted(self.g.reforzar_raiz()), ["acc1-eth1", "acc1-eth2"])

    def test_burst_queda_guardado(self):
        g = GestorColas(cargar(), db=self.db, esperar=False, burst_ms=10, ejecutar=sin_tc)
        g.aplicar("acc1-eth1", 30)
        self.assertEqual(g.leer("acc1-eth1")["colas"][0]["burst"], 300_000)


if __name__ == "__main__":
    unittest.main()
