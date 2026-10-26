"""Pruebas de la estadística de la comparación (PCIII-23).

  python3 -m unittest escenarios.test_estadistica -v
"""
import unittest

from escenarios.estadistica import media_ic, mediana, t95, wilcoxon

try:
    import scipy.stats as st
except ImportError:          # en la VM puede no estar: se prueba igual con valores conocidos
    st = None


class Estadistica(unittest.TestCase):
    def test_media_e_intervalo(self):
        media, mitad = media_ic([10, 12, 14, 16, 18])
        self.assertEqual(media, 14)
        # desvío 3.162; t(4) = 2.776; mitad = 2.776 * 3.162 / sqrt(5) = 3.926
        self.assertAlmostEqual(mitad, 3.926, places=3)
        self.assertEqual(media_ic([7]), (7, None))
        self.assertEqual(media_ic([None]), (None, None))
        self.assertEqual(t95(200), 1.96)

    def test_mediana(self):
        self.assertEqual(mediana([3, 1, 2]), 2)
        self.assertEqual(mediana([4, 1, 2, 3]), 2.5)
        self.assertIsNone(mediana([]))

    def test_wilcoxon_pocos_pares(self):
        r = wilcoxon([1, 2, 3, -1, 0])
        self.assertEqual(r["n"], 4)                      # el cero se descarta
        self.assertIsNone(r["p"])

    def test_wilcoxon_diferencia_clara_y_ninguna(self):
        clara = wilcoxon([30, 25, 41, 33, 28, 35, 22, 39, 31, 27, 36, 29])
        self.assertLess(clara["p"], 0.01)
        mezcla = wilcoxon([3, -2, 1, -4, 2, -1, 4, -3, 5, -5, 2.5, -2.5])
        self.assertGreater(mezcla["p"], 0.5)

    def test_wilcoxon_igual_que_scipy(self):
        d = [12.1, -3.4, 8.8, 15.2, 6.1, 6.1, -1.2, 9.9, 22.4, 4.4, -6.5, 13.3, 7.7, 2.0, 11.0]
        r = wilcoxon(d)
        if st is None:
            self.assertAlmostEqual(r["p"], 0.005866, places=5)     # valor de scipy 1.18
            return
        ref = st.wilcoxon(d, correction=True, method="approx")
        self.assertAlmostEqual(r["p"], ref.pvalue, places=6)
        self.assertEqual(min(r["w_mas"], r["n"] * (r["n"] + 1) / 2 - r["w_mas"]), ref.statistic)



class Analisis(unittest.TestCase):
    """experimentos/analisis.py: qué fases entran y cómo se comparan."""

    @classmethod
    def setUpClass(cls):
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "experimentos"))
        import analisis
        cls.a = analisis

    def escribir(self, filas, descartes=None):
        import csv
        import os
        import tempfile
        import yaml
        d = tempfile.mkdtemp()
        ruta = os.path.join(d, "comparacion.csv")
        campos = sorted({k for f in filas for k in f})
        with open(ruta, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            w.writerows(filas)
        ruta_d = os.path.join(d, "descartes.yaml")
        with open(ruta_d, "w") as f:
            yaml.safe_dump({"descartes": descartes or []}, f)
        return ruta, ruta_d

    def test_deja_fuera_invalidas_descartadas_y_otras_campanas(self):
        base = {"campana": "c1", "sala": 1, "escenario": "sorteo", "fase": "sorteo", "estrategia": "prioridad"}
        filas = [dict(base, semilla=1, valida="sí"), dict(base, semilla=2, valida="no (CPU 95 %)"),
                 dict(base, semilla=3, valida="sí"), dict(base, semilla=4, valida="sí", campana="otra")]
        ruta, ruta_d = self.escribir(filas, [{"archivo": "comparacion.csv", "semilla": 3, "motivo": "x"},
                                             {"archivo": "escenarios.csv", "semilla": 1, "motivo": "otro archivo"}])
        validas, fuera = self.a.cargar("c1", ruta, ruta_d)
        self.assertEqual([r["semilla"] for r in validas], ["1"])
        self.assertEqual(fuera, {"inválidas (CPU)": 1, "descartadas": 1})

    def test_cumplimiento_solo_de_lo_medido(self):
        filas = [{"cumple_voz": "sí", "cumple_pagos": "sí", "cumple_video": ""},
                 {"cumple_voz": "no (latencia p95)", "cumple_pagos": "sí", "cumple_video": "sí"}]
        c = self.a.cumplimiento(filas)
        self.assertEqual((c["voz"], c["pagos"], c["video"], c["web"], c["todos"]), (50.0, 100.0, 100.0, None, 50.0))

    def test_comparacion_en_pares_de_la_misma_semilla(self):
        filas = []
        for semilla in range(1, 13):
            for e, voz in (("fila_corta", 45 + semilla), ("prioridad", 11)):
                filas.append({"sala": "1", "escenario": "x", "fase": "f", "semilla": str(semilla),
                              "estrategia": e, "voz_lat95_ms": str(voz)})
        filas.append({"sala": "1", "escenario": "x", "fase": "f", "semilla": "99", "estrategia": "prioridad",
                      "voz_lat95_ms": "11"})                                # sin pareja: no cuenta
        r = self.a.comparar(filas, "fila_corta", "prioridad", "voz_lat95_ms")
        self.assertEqual(r["pares"], 12)
        self.assertEqual(r["mediana"], -40.5)
        self.assertLess(r["p"], 0.01)


if __name__ == "__main__":
    unittest.main()
