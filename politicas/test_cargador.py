"""Pruebas del cargador de políticas (PCIII-10).

Ejecutar desde la raíz del proyecto:
  python3 -m unittest politicas.test_cargador -v
"""
import copy
import unittest

import yaml

from politicas.cargador import (POLITICAS_DEFECTO, PoliticaInvalida, Politicas, cargar,
                                vocabulario_empresa)


def base():
    with open(POLITICAS_DEFECTO) as f:
        return yaml.safe_load(f)


class Validacion(unittest.TestCase):
    def test_archivo_real_es_valido(self):
        pol = cargar()
        self.assertEqual(len(pol.clases), 6)
        self.assertEqual(pol.clases[0]["nombre"], "tiempo_real")

    def rechaza(self, datos, fragmento):
        with self.assertRaises(PoliticaInvalida) as ctx:
            Politicas(datos, vocabulario_empresa())
        self.assertTrue(any(fragmento in e for e in ctx.exception.errores),
                        f"se esperaba un error con '{fragmento}', hubo: {ctx.exception.errores}")

    def test_suma_de_garantias_mayor_a_100(self):
        d = base()
        d["clases"][0]["garantia_pct"] = 60
        self.rechaza(d, "suma de garantías")

    def test_techo_menor_que_garantia(self):
        d = base()
        d["clases"][1]["techo_pct"] = 5
        self.rechaza(d, "techo")

    def test_garantia_cero(self):
        d = base()
        d["clases"][5]["garantia_pct"] = 0
        self.rechaza(d, "mayor que 0")

    def test_regla_con_clase_inexistente(self):
        d = base()
        d["reglas"][0]["clase"] = "vip"
        self.rechaza(d, "clase inexistente")

    def test_regla_con_segmento_mal_escrito(self):
        d = base()
        d["reglas"][0]["segmento"] = "wifi_cliente"
        self.rechaza(d, "segmento desconocido")

    def test_regla_con_tipo_mal_escrito(self):
        d = base()
        d["reglas"][1]["tipo"] = "pc_musik"
        self.rechaza(d, "tipo de equipo desconocido")

    def test_prioridad_repetida(self):
        d = base()
        d["clases"][1]["prioridad"] = 0
        self.rechaza(d, "prioridad 0 repetida")

    def test_falta_objetivo(self):
        d = base()
        del d["objetivos"]["mos_min"]
        self.rechaza(d, "mos_min")

    def test_servicio_de_internet_sin_clase(self):
        d = base()
        del d["servicios_por_defecto"]["pagos"]
        self.rechaza(d, "'pagos'")

    def test_reporta_todos_los_errores_juntos(self):
        d = copy.deepcopy(base())
        d["clases"][0]["garantia_pct"] = 90
        d["reglas"][0]["clase"] = "vip"
        with self.assertRaises(PoliticaInvalida) as ctx:
            Politicas(d, vocabulario_empresa())
        self.assertGreaterEqual(len(ctx.exception.errores), 2)


class Clasificacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pol = cargar()

    def clase(self, tipo, segmento, servicio):
        return self.pol.clasificar(segmento, tipo, servicio)[0]

    def test_maquinas_reportando_son_criticas(self):
        self.assertEqual(self.clase("tragamonedas", "maquinas", "gestion"), "critico")

    def test_respaldo_del_servidor_de_sala_no_es_critico(self):
        self.assertEqual(self.clase("servidor_sala", "maquinas", "respaldo"), "masivo")

    def test_pagos_son_criticos(self):
        self.assertEqual(self.clase("pos", "pagos", "pagos"), "critico")

    def test_telefono_es_tiempo_real(self):
        self.assertEqual(self.clase("telefono_ip", "administracion", "voip"), "tiempo_real")

    def test_misma_app_distinto_equipo(self):
        # YouTube: música de la sala es negocio; clientes del WiFi, restringido.
        self.assertEqual(self.clase("pc_musica", "administracion", "streaming"), "negocio")
        self.assertEqual(self.clase("cliente_wifi", "wifi_clientes", "streaming"), "restringido")

    def test_ia_generativa_segun_area(self):
        self.assertEqual(self.clase("pc_sistemas", "administracion", "ia_generativa"), "negocio")
        self.assertEqual(self.clase("pc_contabilidad", "administracion", "ia_generativa"), "masivo")

    def test_wifi_clientes_restringido_aunque_sea_voz(self):
        self.assertEqual(self.clase("cliente_wifi", "wifi_clientes", "voip"), "restringido")

    def test_servicio_desconocido(self):
        self.assertEqual(self.clase("pc_caja", "administracion", "juego_raro"), "masivo")

    def test_servicio_de_destino(self):
        self.assertEqual(self.pol.servicio_de({"segmento": "servidores", "tipo": "central_telefonica"}), "voip")
        self.assertEqual(self.pol.servicio_de({"segmento": "internet", "tipo": "streaming"}), "streaming")
        self.assertEqual(self.pol.servicio_de({"segmento": "cctv", "tipo": "camara_ip"}), "desconocido")


class Tasas(unittest.TestCase):
    def test_tasas_para_10_mbps(self):
        t = cargar().tasas(10)
        self.assertEqual(t["tiempo_real"], (1_500_000, 4_000_000))
        self.assertEqual(t["restringido"], (200_000, 2_000_000))
        self.assertLessEqual(sum(r for r, _ in t.values()), 10_000_000)


if __name__ == "__main__":
    unittest.main()
