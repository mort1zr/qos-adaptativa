"""
Clasificadores de flujos (historia PCIII-19).

El controlador decide la clase de cada flujo NUEVO con el primer paquete
(packet-in) y la deja escrita en una regla OpenFlow con set_queue; el resto de
los paquetes del flujo ya no pasan por el controlador. Quién decide la clase
es un "clasificador" intercambiable con una sola operación:

    clasificar(flujo) -> Decision(clase, motivo)

Hoy hay dos:
  ninguno   no clasifica: todo va a la cola por defecto (la de "desconocido").
            Es lo que hacen las estrategias sin_qos y fila_corta.
  politica  aplica politicas/politicas.yaml con lo que se sabe del flujo: el
            equipo de la sede (segmento, tipo) y el servicio del otro extremo.

Después se enchufan aquí el clasificador por tabla de destinos (PCIII-20) y el
de aprendizaje automático (Sprint 4), sin tocar la aplicación de Ryu.

No depende de Ryu. Compatible con Python 3.9.
"""
import time
from dataclasses import dataclass
from typing import Dict, Optional, Type


@dataclass(frozen=True)
class Flujo:
    """Lo que el controlador sabe de un flujo cuando ve su primer paquete."""
    sede_id: Optional[int]
    sentido: str                  # "subida" (sale de la sede) o "bajada" (entra a la sede)
    origen_ip: str
    destino_ip: str
    proto: int
    local: Optional[dict] = None  # equipo del inventario que está en la sede del switch
    remoto: Optional[dict] = None  # el otro extremo, si está en el inventario
    ts: float = 0.0


@dataclass(frozen=True)
class Decision:
    clase: str
    motivo: str


def armar_flujo(inv, sw: dict, origen_ip: str, destino_ip: str, proto: int, in_port: int,
                ts: Optional[float] = None) -> Flujo:
    """Arma el Flujo visto en un switch de acceso: sentido, equipo local y remoto."""
    sede = sw["sede_id"]
    sentido = "subida" if in_port == sw["puerto_sede"] else "bajada"
    o, d = inv.equipo(origen_ip), inv.equipo(destino_ip)
    if o and o["sede_id"] == sede:
        local, remoto = o, d
    elif d and d["sede_id"] == sede:
        local, remoto = d, o
    else:
        local, remoto = None, None
    return Flujo(sede, sentido, origen_ip, destino_ip, proto, local, remoto,
                 time.time() if ts is None else ts)


class Clasificador:
    """Base: un clasificador recibe un Flujo y devuelve una Decision."""
    nombre = "base"
    descripcion = ""

    def __init__(self, politicas):
        self.pol = politicas

    def clasificar(self, flujo: Flujo) -> Decision:
        raise NotImplementedError


class SinClasificar(Clasificador):
    nombre = "ninguno"
    descripcion = "todo a la cola por defecto (sin_qos, fila_corta)"

    def clasificar(self, flujo: Flujo) -> Decision:
        return Decision(self.pol.defecto["desconocido"], "sin clasificar")


class PorPolitica(Clasificador):
    nombre = "politica"
    descripcion = "reglas de politicas.yaml según el equipo de la sede y el servicio del otro extremo"

    def servicio(self, flujo: Flujo) -> str:
        # El servicio lo define el lado que actúa como servidor: normalmente el otro
        # extremo (Internet, la central); si ese no ofrece nada (p. ej. la PC de
        # monitoreo que mira las cámaras), el servicio es el del equipo local (el NVR).
        servicio = self.pol.servicio_de(flujo.remoto) if flujo.remoto else "desconocido"
        if servicio == "desconocido" and flujo.local:
            servicio = self.pol.servicio_de(flujo.local)
        return servicio

    def clasificar(self, flujo: Flujo) -> Decision:
        if not flujo.local:
            return Decision(self.pol.defecto["desconocido"], "equipo fuera del inventario")
        clase, motivo = self.pol.clasificar(flujo.local["segmento"], flujo.local["tipo"],
                                            self.servicio(flujo))
        return Decision(clase, motivo)


CLASIFICADORES: Dict[str, Type[Clasificador]] = {c.nombre: c for c in (SinClasificar, PorPolitica)}


def crear(nombre: str, politicas) -> Clasificador:
    if nombre not in CLASIFICADORES:
        raise ValueError(f"clasificador desconocido: {nombre} (hay: {', '.join(CLASIFICADORES)})")
    return CLASIFICADORES[nombre](politicas)
