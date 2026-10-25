"""
Reloj simulado de los escenarios (historia PCIII-18).

Un escenario empieza en un día y una hora de la semana (por ejemplo, sábado
20:50) y su tiempo corre 'factor' veces más rápido que el real: con factor 12,
10 minutos reales son 2 horas de jornada. Así el sistema puede "ver" la hora y
el día sin esperar horas reales. La semana de referencia es la del lunes 2 de
noviembre de 2026.

El escenario en curso escribe datos/reloj.json; cualquier componente (el
predictor del Sprint 4, por ejemplo) puede leerlo con leer_reloj() para saber
qué hora simulada es ahora.
"""
import datetime
import json
import os
import time
from typing import Optional

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELOJ = os.path.join(RAIZ, "datos", "reloj.json")
LUNES_REFERENCIA = datetime.date(2026, 11, 2)
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def normalizar_dia(dia: str) -> str:
    return dia.lower().replace("é", "e").replace("á", "a")


class RelojSimulado:
    def __init__(self, dia: str, hora: str, factor: float = 12, inicio_real: Optional[float] = None):
        dia = normalizar_dia(dia)
        if dia not in DIAS:
            raise ValueError(f"día desconocido: {dia} (usa {', '.join(DIAS)})")
        hh, mm = (int(x) for x in hora.split(":"))
        fecha = LUNES_REFERENCIA + datetime.timedelta(days=DIAS.index(dia))
        self.inicio_simulado = datetime.datetime.combine(fecha, datetime.time(hh, mm))
        self.factor = factor
        self.inicio_real = time.time() if inicio_real is None else inicio_real

    def simulado(self, t_real: Optional[float] = None) -> datetime.datetime:
        """Fecha y hora simuladas que corresponden a un instante real."""
        t_real = time.time() if t_real is None else t_real
        return self.inicio_simulado + datetime.timedelta(seconds=(t_real - self.inicio_real) * self.factor)

    def describir(self, t_real: Optional[float] = None) -> str:
        s = self.simulado(t_real)
        return f"{DIAS[s.weekday()]} {s:%H:%M}"

    def guardar(self, escenario: str, fase: str, ruta: str = RELOJ, **extra):
        """Publica el reloj en datos/reloj.json para otros componentes."""
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w") as f:
            json.dump({"escenario": escenario, "fase": fase, "inicio_real": self.inicio_real,
                       "inicio_simulado": self.inicio_simulado.isoformat(), "factor": self.factor,
                       **extra}, f)


def leer_reloj(ruta: str = RELOJ) -> Optional[RelojSimulado]:
    """El reloj del escenario en curso (o del último), o None si no hay."""
    try:
        with open(ruta) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    inicio = datetime.datetime.fromisoformat(d["inicio_simulado"])
    r = RelojSimulado(DIAS[inicio.weekday()], f"{inicio:%H:%M}", d["factor"], d["inicio_real"])
    r.inicio_simulado = inicio
    return r
