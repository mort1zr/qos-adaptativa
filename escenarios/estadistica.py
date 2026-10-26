"""
Estadística para comparar estrategias (PCIII-23; punto 1 de las mejoras de evidencia).

Sin dependencias (ni numpy ni scipy): corre con el Python del sistema.

  media_ic(valores)          promedio e intervalo de confianza del 95 % (t de Student)
  wilcoxon(diferencias)      prueba de rangos con signo de Wilcoxon, dos colas, con la
                             aproximación normal (corrección por empates y continuidad).
                             Es la prueba habitual para comparar dos estrategias medidas en
                             las MISMAS condiciones (pares: sala, escenario, fase, semilla)
                             sin suponer que las diferencias son normales.

Con menos de 10 pares la aproximación normal no es confiable: se informa "pocos pares"
en lugar de un p-valor. Por eso las pruebas se hacen uniendo los escenarios; por
escenario se informan promedios con su intervalo.
"""
import math
from typing import List, Optional, Tuple

# t de Student, dos colas, 95 %, para 1..30 grados de libertad (con más, ~1.96).
T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
       2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
       2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]
MIN_PARES = 10


def t95(gl: int) -> float:
    return T95[gl - 1] if 1 <= gl <= len(T95) else 1.96


def media_ic(valores: List[float]) -> Tuple[Optional[float], Optional[float]]:
    """(promedio, mitad del intervalo del 95 %). Con un solo valor, sin intervalo."""
    v = [x for x in valores if x is not None]
    if not v:
        return None, None
    media = sum(v) / len(v)
    if len(v) < 2:
        return media, None
    desvio = math.sqrt(sum((x - media) ** 2 for x in v) / (len(v) - 1))
    return media, t95(len(v) - 1) * desvio / math.sqrt(len(v))


def mediana(valores: List[float]) -> Optional[float]:
    v = sorted(x for x in valores if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def _normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def wilcoxon(diferencias: List[float]) -> dict:
    """Wilcoxon de rangos con signo, dos colas. Las diferencias cero se descartan
    (método de Wilcoxon). Devuelve n (pares sin empate), W+ y p (None si hay pocos pares)."""
    d = [x for x in diferencias if x is not None and x != 0]
    n = len(d)
    if n < MIN_PARES:
        return {"n": n, "w_mas": None, "z": None, "p": None}
    orden = sorted(range(n), key=lambda i: abs(d[i]))
    rangos = [0.0] * n
    empates = 0.0
    i = 0
    while i < n:                                   # rangos promedio para |d| empatados
        j = i
        while j + 1 < n and abs(d[orden[j + 1]]) == abs(d[orden[i]]):
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rangos[orden[k]] = r
        t = j - i + 1
        empates += t ** 3 - t
        i = j + 1
    w_mas = sum(r for r, x in zip(rangos, d) if x > 0)
    media = n * (n + 1) / 4
    varianza = n * (n + 1) * (2 * n + 1) / 24 - empates / 48
    if varianza <= 0:
        return {"n": n, "w_mas": w_mas, "z": 0.0, "p": 1.0}
    z = (abs(w_mas - media) - 0.5) / math.sqrt(varianza)   # con corrección de continuidad
    p = min(1.0, 2 * (1 - _normal_cdf(max(z, 0.0))))
    return {"n": n, "w_mas": w_mas, "z": round(z, 3), "p": p}
