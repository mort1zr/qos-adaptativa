#!/usr/bin/env python3
"""
QoS estática por horario (historia PCIII-21).

Aplica a los enlaces de acceso los techos de politicas/horario.yaml según la
franja horaria del reloj simulado: es la estrategia 'estatica' de los
escenarios, la línea base con reglas fijas contra la que se comparará la IA.
Solo mira la hora; nunca la demanda.

  python3 controlador/estatica.py ver --mbps 30          # franjas y techos de un enlace
  python3 controlador/estatica.py ver --mbps 10 --hora 15:00

El motor (QoSEstatica) lo usa escenarios/escenario.py: revisa el reloj cada
segundo y, cuando cambia la franja, cambia los techos de las colas en todos
los enlaces de acceso con GestorColas.cambiar (en caliente, sin cortar el
tráfico). Necesita sudo, como el resto de la configuración de colas.
"""
import argparse
import os
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from politicas.cargador import Politicas, cargar  # noqa: E402

HORARIO = os.path.join(RAIZ, "politicas", "horario.yaml")
MINUTOS_DIA = 24 * 60


class HorarioInvalido(ValueError):
    pass


def _minutos(texto: str) -> int:
    hh, mm = (int(x) for x in str(texto).split(":"))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError(texto)
    return hh * 60 + mm


class Horario:
    def __init__(self, datos: dict, politicas: Politicas):
        self.pol = politicas
        errores, self.franjas = [], []
        for i, f in enumerate(datos.get("franjas") or [], 1):
            nombre = f.get("nombre") or f"franja {i}"
            try:
                desde, hasta = _minutos(f.get("desde")), _minutos(f.get("hasta"))
            except (ValueError, TypeError):
                errores.append(f"{nombre}: 'desde' y 'hasta' deben ser HH:MM")
                continue
            techos = dict(f.get("techos_pct") or {})
            for clase, pct in techos.items():
                c = politicas.por_nombre.get(clase)
                if not c:
                    errores.append(f"{nombre}: clase desconocida '{clase}'")
                elif not isinstance(pct, (int, float)) or not 0 < pct <= 100:
                    errores.append(f"{nombre}: el techo de '{clase}' debe estar entre 1 y 100 %")
                elif pct < c["garantia_pct"]:
                    errores.append(f"{nombre}: el techo de '{clase}' ({pct} %) es menor que su "
                                   f"garantía ({c['garantia_pct']} %)")
            self.franjas.append({"nombre": nombre, "descripcion": f.get("descripcion", ""),
                                 "desde": desde, "hasta": hasta, "techos_pct": techos})
        if not self.franjas and not errores:
            errores.append("se necesita al menos una franja")
        if not errores:
            cubiertos = [0] * MINUTOS_DIA
            for f in self.franjas:
                for m in self._minutos_de(f):
                    cubiertos[m] += 1
            if any(c > 1 for c in cubiertos):
                errores.append("hay franjas que se pisan")
            sin = [m for m, c in enumerate(cubiertos) if c == 0]
            if sin:
                errores.append(f"las franjas no cubren todo el día (falta desde las {sin[0] // 60:02d}:{sin[0] % 60:02d})")
        if errores:
            raise HorarioInvalido("Horario inválido:\n  - " + "\n  - ".join(errores))

    @staticmethod
    def _minutos_de(f):
        m = f["desde"]
        while True:
            yield m
            m = (m + 1) % MINUTOS_DIA
            if m == f["hasta"]:
                return

    def franja(self, cuando) -> dict:
        """La franja de una hora (datetime, time o 'HH:MM')."""
        if isinstance(cuando, str):
            m = _minutos(cuando)
        else:
            m = cuando.hour * 60 + cuando.minute
        for f in self.franjas:
            d, h = f["desde"], f["hasta"]
            if (d <= m < h) if d < h else (m >= d or m < h):
                return f
        raise HorarioInvalido(f"ninguna franja cubre las {m // 60:02d}:{m % 60:02d}")

    def clases_controladas(self) -> List[str]:
        """Clases cuyo techo cambia en alguna franja (las demás nunca se tocan)."""
        return sorted({c for f in self.franjas for c in f["techos_pct"]})

    def techos(self, franja: dict, mbps: float) -> Dict[str, int]:
        """Techo (bit/s) de cada clase controlada en esa franja, para un enlace de 'mbps'."""
        defecto = self.pol.tasas(mbps)
        bps = mbps * 1_000_000
        return {c: int(bps * franja["techos_pct"][c] / 100) if c in franja["techos_pct"] else defecto[c][1]
                for c in self.clases_controladas()}


def cargar_horario(politicas: Optional[Politicas] = None, ruta: str = HORARIO) -> Horario:
    import yaml
    with open(ruta) as f:
        return Horario(yaml.safe_load(f) or {}, politicas or cargar())


class QoSEstatica:
    """Aplica el horario a los enlaces de acceso cuando cambia la franja del reloj simulado."""

    def __init__(self, gestor, puertos: List[Tuple[str, float]], horario: Horario,
                 leer_reloj: Optional[Callable] = None, avisar: Callable = print):
        if leer_reloj is None:
            from escenarios.reloj import leer_reloj
        self.gestor, self.puertos, self.horario = gestor, puertos, horario
        self.leer_reloj, self.avisar = leer_reloj, avisar
        self.actual: Optional[str] = None
        self.cambios: List[dict] = []
        self._hilo, self._parar = None, threading.Event()
        # El escenario (al empezar) y el hilo (cada segundo) llaman a paso(): nunca a la vez,
        # para no escribir dos veces en Open vSwitch ni dejar una cola a medio cambiar.
        self._candado = threading.Lock()

    def paso(self, ahora: Optional[float] = None) -> Optional[str]:
        """Revisa la hora simulada y, si la franja cambió, aplica sus techos. Devuelve la franja."""
        with self._candado:
            return self._paso(ahora)

    def _paso(self, ahora: Optional[float]) -> Optional[str]:
        reloj = self.leer_reloj()
        if reloj is None:
            return self.actual
        simulado = reloj.simulado(ahora)
        f = self.horario.franja(simulado)
        if f["nombre"] == self.actual:
            return self.actual
        t0 = time.time()
        for puerto, mbps in self.puertos:
            for clase, techo in self.horario.techos(f, mbps).items():
                self.gestor.cambiar(puerto, clase, max_rate=techo)
        anterior, self.actual = self.actual, f["nombre"]
        self.cambios.append({"hora_simulada": simulado.strftime("%a %H:%M"), "de": anterior, "a": f["nombre"],
                             "segundos": round(time.time() - t0, 2)})
        enlaces = sorted({mbps for _, mbps in self.puertos})
        resumen = "; ".join(
            ", ".join(f"{c} {t / 1e6:g}" for c, t in self.horario.techos(f, mbps).items()) + f" de {mbps:g}"
            for mbps in enlaces)
        self.avisar(f"    [estatica] {simulado:%H:%M} (simulado): franja '{f['nombre']}', techos en Mbps: "
                    f"{resumen} ({len(self.puertos)} puertos en {time.time() - t0:.1f} s)")
        return self.actual

    def iniciar(self, cada_s: float = 1.0):
        self._parar.clear()

        def bucle():
            while not self._parar.wait(cada_s):
                try:
                    self.paso()
                except Exception as e:          # el motor no debe tumbar el escenario
                    self.avisar(f"    [estatica] error al aplicar el horario: {e}")
        self._hilo = threading.Thread(target=bucle, daemon=True)
        self._hilo.start()

    def detener(self):
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=10)
        self._hilo = None
        self.actual = None


def main():
    p = argparse.ArgumentParser(description="QoS estática por horario (PCIII-21)")
    sub = p.add_subparsers(dest="accion", required=True)
    v = sub.add_parser("ver", help="franjas y techos para un enlace")
    v.add_argument("--mbps", type=float, default=30)
    v.add_argument("--hora", help="HH:MM: muestra qué franja rige a esa hora")
    args = p.parse_args()
    try:
        h = cargar_horario()
    except HorarioInvalido as e:
        sys.exit(str(e))
    print(f"Horario de la QoS estática para un enlace de {args.mbps:g} Mbps (clases que cambian: "
          f"{', '.join(h.clases_controladas()) or 'ninguna'}):")
    for f in h.franjas:
        techos = ", ".join(f"{c} techo {t / 1e6:.1f} Mbps" for c, t in h.techos(f, args.mbps).items())
        print(f"  {f['nombre']:10s} {f['desde'] // 60:02d}:{f['desde'] % 60:02d}-{f['hasta'] // 60:02d}:"
              f"{f['hasta'] % 60:02d}  {techos}\n             {f['descripcion']}")
    if args.hora:
        print(f"A las {args.hora} rige la franja '{h.franja(args.hora)['nombre']}'.")


if __name__ == "__main__":
    main()
