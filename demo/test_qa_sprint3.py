"""Evita falsos aprobados y acciones sobre escenarios ajenos en el ejecutor QA."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from demo.qa_sprint3 import evaluar_comparacion, FalloQA, QA


def ejemplo():
    """Datos sintéticos solo para verificar el validador, nunca son evidencia real."""
    corridas, filas = [], []
    for estrategia in ("sin_qos", "prioridad"):
        fases = []
        for nombre in ("normal", "respaldo", "normal_otra_vez"):
            metricas = {"cpu_pct": 40, "voz_lat95_ms": 20, "voz_mos": 4.2,
                        "pagos_p95_ms": 30, "web_p95_ms": 400, "pagos_n": 10, "web_n": 3}
            fases.append({"nombre": nombre, "estado": "terminada", "metricas": metricas, "valida": True})
            filas.append({"estrategia": estrategia, "fase": nombre, "sala": "1",
                          "escenario": "respaldo_en_atencion", **{k: str(v) for k, v in metricas.items()}})
        corridas.append({"estrategia": estrategia, "escenario": "respaldo_en_atencion", "fases": fases})
    return {"estado": "terminado", "parametros": {"sala": 1}, "corridas": corridas}, filas


class ValidadorComparacion(unittest.TestCase):
    def test_seis_fases_con_csv_coincidente(self):
        resultado = evaluar_comparacion(*ejemplo())
        self.assertEqual(len(resultado["fases"]), 6)
        self.assertEqual(resultado["invalidas"], [])

    def test_cpu_alta_es_inconclusa(self):
        progreso, filas = ejemplo()
        progreso["corridas"][0]["fases"][0]["metricas"]["cpu_pct"] = 90
        filas[0]["cpu_pct"] = "90"
        self.assertEqual(evaluar_comparacion(progreso, filas)["invalidas"], ["sin_qos/normal"])

    def test_fase_marcada_invalida_no_se_aprueba(self):
        progreso, filas = ejemplo()
        progreso["corridas"][0]["fases"][0]["valida"] = False
        self.assertTrue(evaluar_comparacion(progreso, filas)["invalidas"])

    def test_csv_viejo_duplicado_incompleto_o_divergente(self):
        progreso, filas = ejemplo()
        distintos = copy.deepcopy(filas)
        distintos[0]["voz_mos"] = "1.0"
        for csv in (filas[:-1], filas + [filas[0]], filas[:3] + filas[:3], distintos):
            with self.subTest(csv=csv), self.assertRaises(FalloQA):
                evaluar_comparacion(progreso, csv)

    def test_metricas_ausentes_nan_inf_o_sin_transacciones(self):
        for campo, valor in (("cpu_pct", None), ("voz_mos", float("nan")),
                             ("web_p95_ms", float("inf")), ("pagos_n", 0)):
            progreso, filas = ejemplo()
            progreso["corridas"][0]["fases"][0]["metricas"][campo] = valor
            with self.subTest(campo=campo), self.assertRaises(FalloQA):
                evaluar_comparacion(progreso, filas)

    def test_progreso_cancelado_o_sala_incorrecta(self):
        for campo, valor in (("estado", "cancelado"), ("parametros", {"sala": 2})):
            progreso, filas = ejemplo()
            progreso[campo] = valor
            with self.subTest(campo=campo), self.assertRaises(FalloQA):
                evaluar_comparacion(progreso, filas)


class ProteccionLaboratorio(unittest.TestCase):
    def test_api_caida_no_equivale_a_red_limpia(self):
        with tempfile.TemporaryDirectory() as carpeta:
            qa = QA(Path(carpeta))
            qa.http = Mock(side_effect=[FalloQA("API reiniciando", 503), {"switches_conectados": []}])
            self.assertFalse(qa.desconectada())
            self.assertTrue(qa.desconectada())
            self.assertTrue(qa.espera_api_tras_limpieza)

    def test_no_oculta_otros_errores_de_api(self):
        with tempfile.TemporaryDirectory() as carpeta:
            qa = QA(Path(carpeta))
            qa.http = Mock(side_effect=FalloQA("Error interno", 500))
            with self.assertRaises(FalloQA):
                qa.desconectada()

    def test_no_cancela_un_escenario_ajeno(self):
        with tempfile.TemporaryDirectory() as carpeta:
            qa = QA(Path(carpeta))
            qa.estado = Mock(return_value={"vista_previa": False,
                                          "controlador": {"modo": "docker", "api": True},
                                          "trabajo": {"tipo": "escenario", "estado": "corriendo"}})
            qa.http = Mock()
            with self.assertRaises(FalloQA):
                qa.precondicion_red()
            self.assertFalse(qa.red_autorizada)
            qa.http.assert_not_called()

    def test_no_detiene_un_trabajo_reemplazado(self):
        with tempfile.TemporaryDirectory() as carpeta:
            qa = QA(Path(carpeta))
            qa.trabajo_propio = 10
            qa.estado = Mock(return_value={"trabajo": {"inicio": 20, "estado": "corriendo"}})
            qa.http = Mock()
            with self.assertRaises(FalloQA):
                qa.detener()
            qa.http.assert_not_called()

    def test_inconcluso_no_se_convierte_en_aprobado(self):
        with tempfile.TemporaryDirectory() as carpeta:
            qa = QA(Path(carpeta))
            self.assertTrue(qa.caso("QA-06", "CPU alta", lambda: {"invalidas": ["normal"]}))
            self.assertEqual(qa.casos[0]["estado"], "INCONCLUSO")


if __name__ == "__main__":
    unittest.main()
