"""
Clasificadores de flujos (historia PCIII-19).

El controlador decide la clase de cada flujo NUEVO con el primer paquete
(packet-in) y la deja escrita en una regla OpenFlow con set_queue; el resto de
los paquetes del flujo ya no pasan por el controlador. Quién decide la clase
es un "clasificador" intercambiable con una sola operación:

    clasificar(flujo) -> Decision(clase, motivo)

Hoy hay tres:
  ninguno   no clasifica: todo va a la cola por defecto (la de "desconocido").
            Es lo que hacen las estrategias sin_qos y fila_corta.
  politica  aplica politicas/politicas.yaml sabiendo TODO del otro extremo
            (incluso qué es cada servidor de Internet). Es la "etiqueta
            verdadera": la usa la telemetría y servirá para entrenar a la IA.
  destino   lo que haría una empresa real (PCIII-20): sus propios equipos los
            conoce por su inventario, pero de Internet solo sabe lo que dice
            la tabla de destinos (politicas/destinos.yaml), como las listas
            que publican Microsoft o Zoom. Lo que no está en la tabla queda
            "desconocido" (lo resolverá la IA del Sprint 4). Además puede
            instalar sus reglas POR ADELANTADO (reglas_proactivas): el primer
            paquete ya no espera al controlador.

El de aprendizaje automático (Sprint 4) se enchufa aquí sin tocar Ryu.

No depende de Ryu. Compatible con Python 3.9.
"""
import ipaddress
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Type

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINOS = os.path.join(RAIZ, "politicas", "destinos.yaml")


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

    @property
    def ip_remota(self) -> str:
        """IP del otro extremo (el que no está en la sede del switch)."""
        if self.local and self.local.get("ip") == self.origen_ip:
            return self.destino_ip
        if self.local and self.local.get("ip") == self.destino_ip:
            return self.origen_ip
        return self.destino_ip


@dataclass(frozen=True)
class Decision:
    clase: str
    motivo: str
    servicio: str = ""            # el servicio reconocido ("desconocido" si no se supo)


@dataclass(frozen=True)
class ReglaProactiva:
    """Regla que el controlador instala antes de que llegue el tráfico.
    'local' es una red (o equipo) de la sede y 'remota' un destino conocido."""
    local: str
    remota: str
    clase: str
    motivo: str
    servicio: str


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

    def reglas_proactivas(self, equipos: List[dict], sede_id) -> List[ReglaProactiva]:
        """Reglas para instalar por adelantado en el switch de acceso de 'sede_id'.
        'equipos' es todo el inventario. Por defecto ninguna: todo se decide con el
        primer paquete."""
        return []


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
            return Decision(self.pol.defecto["desconocido"], "equipo fuera del inventario", "desconocido")
        servicio = self.servicio(flujo)
        clase, motivo = self.pol.clasificar(flujo.local["segmento"], flujo.local["tipo"], servicio)
        return Decision(clase, motivo, servicio)


# ---------------- tabla de destinos (PCIII-20) ----------------
class TablaInvalida(ValueError):
    pass


@dataclass(frozen=True)
class Destino:
    red: ipaddress.IPv4Network
    servicio: str
    proveedor: str


class TablaDestinos:
    """Redes de Internet conocidas por servicio (politicas/destinos.yaml)."""

    def __init__(self, datos: dict, servicios_validos=None):
        errores, self.destinos = [], []
        for i, d in enumerate(datos.get("destinos") or [], 1):
            proveedor = d.get("proveedor") or f"destino {i}"
            servicio = d.get("servicio")
            if servicios_validos is not None and servicio not in servicios_validos:
                errores.append(f"{proveedor}: servicio desconocido '{servicio}' (no está en politicas.yaml)")
            if not d.get("redes"):
                errores.append(f"{proveedor}: necesita al menos una red")
            for red in d.get("redes") or []:
                try:
                    self.destinos.append(Destino(ipaddress.ip_network(red), servicio, proveedor))
                except ValueError:
                    errores.append(f"{proveedor}: red inválida '{red}' (usa CIDR, p. ej. 203.0.113.8/29)")
        for i, a in enumerate(self.destinos):
            for b in self.destinos[i + 1:]:
                if a.red.overlaps(b.red):
                    errores.append(f"las redes se pisan: {a.red} ({a.proveedor}) y {b.red} ({b.proveedor})")
        if errores:
            raise TablaInvalida("Tabla de destinos inválida:\n  - " + "\n  - ".join(errores))

    def buscar(self, ip: str) -> Optional[Destino]:
        try:
            dir_ip = ipaddress.ip_address(ip)
        except ValueError:
            return None
        for d in self.destinos:
            if dir_ip in d.red:
                return d
        return None


def cargar_tabla(politicas, ruta: str = DESTINOS) -> TablaDestinos:
    import yaml
    with open(ruta) as f:
        return TablaDestinos(yaml.safe_load(f) or {}, servicios_validos=set(politicas.defecto))


class PorDestino(Clasificador):
    nombre = "destino"
    descripcion = ("tabla de destinos de Internet + servidores propios del inventario; "
                   "lo que no está en la tabla queda 'desconocido'; reglas por adelantado")

    def __init__(self, politicas, tabla: Optional[TablaDestinos] = None):
        super().__init__(politicas)
        self.tabla = tabla or cargar_tabla(politicas)

    @staticmethod
    def _es_propio(equipo: Optional[dict]) -> bool:
        """Equipo de la empresa (tiene sede), no un servidor de Internet."""
        return bool(equipo) and equipo.get("sede_id") is not None

    def servicio(self, flujo: Flujo) -> Tuple[str, str]:
        """(servicio, de dónde se supo) del otro extremo del flujo."""
        if self._es_propio(flujo.remoto):
            servicio, fuente = self.pol.servicio_de(flujo.remoto), f"servidor propio {flujo.remoto['nombre']}"
        else:
            d = self.tabla.buscar(flujo.ip_remota)
            servicio, fuente = (d.servicio, d.proveedor) if d else ("desconocido", "destino fuera de la tabla")
        if servicio == "desconocido" and flujo.local:
            propio = self.pol.servicio_de(flujo.local)          # p. ej. el NVR que sirve el video
            if propio != "desconocido":
                servicio, fuente = propio, f"servicio del equipo local {flujo.local['nombre']}"
        return servicio, fuente

    def clasificar(self, flujo: Flujo) -> Decision:
        if not flujo.local:
            return Decision(self.pol.defecto["desconocido"], "equipo fuera del inventario", "desconocido")
        servicio, fuente = self.servicio(flujo)
        clase, motivo = self.pol.clasificar(flujo.local["segmento"], flujo.local["tipo"], servicio)
        return Decision(clase, f"{fuente} · {motivo}", servicio)

    def destinos_conocidos(self, equipos: List[dict], sede_id) -> List[Tuple[str, str, str]]:
        """(red, servicio, proveedor) que se conocen de antemano desde una sede: la tabla
        de Internet y los servidores propios de OTRAS sedes que ofrecen un servicio."""
        conocidos = [(str(d.red), d.servicio, d.proveedor) for d in self.tabla.destinos]
        for e in equipos:
            if self._es_propio(e) and e["sede_id"] != sede_id:
                servicio = self.pol.servicio_de(e)
                if servicio != "desconocido":
                    conocidos.append((f"{e['ip']}/32", servicio, f"servidor propio {e['nombre']}"))
        return conocidos

    def reglas_proactivas(self, equipos: List[dict], sede_id) -> List[ReglaProactiva]:
        """Compila la política como lo haría una lista de acceso: por cada segmento de la
        sede y cada destino conocido, una regla con la red del segmento; si dentro del
        segmento la clase depende del tipo de equipo (la PC de música, las de Sistemas),
        una regla por equipo."""
        grupos: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
        for e in equipos:
            if e.get("sede_id") == sede_id and e.get("ip"):
                grupos[(e["segmento"], e.get("gateway") or "")].append(e)
        conocidos = self.destinos_conocidos(equipos, sede_id)
        reglas = []
        for (segmento, gateway), miembros in sorted(grupos.items()):
            red = _red_del_segmento(gateway, miembros)
            for remota, servicio, fuente in conocidos:
                por_equipo = {e["ip"]: self.pol.clasificar(segmento, e["tipo"], servicio) for e in miembros}
                if red and len({c for c, _ in por_equipo.values()}) == 1:
                    clase, motivo = next(iter(por_equipo.values()))
                    reglas.append(ReglaProactiva(red, remota, clase, f"{fuente} · {motivo}", servicio))
                else:
                    for ip, (clase, motivo) in sorted(por_equipo.items()):
                        reglas.append(ReglaProactiva(f"{ip}/32", remota, clase, f"{fuente} · {motivo}", servicio))
        return reglas


def red_para_openflow(texto: str):
    """'10.1.20.0/24' -> ('10.1.20.0', '255.255.255.0'), como lo pide OFPMatch de Ryu;
    una /32 (o una IP sola) queda como IP."""
    red = ipaddress.ip_network(texto, strict=False)
    if red.prefixlen == 32:
        return str(red.network_address)
    return str(red.network_address), str(red.netmask)


def _red_del_segmento(gateway: str, miembros: List[dict]) -> Optional[str]:
    """La red /24 del segmento (la de su puerta de enlace), si todos sus equipos están en ella."""
    try:
        red = ipaddress.ip_interface(f"{gateway}/24").network
    except ValueError:
        return None
    if all(ipaddress.ip_address(e["ip"]) in red for e in miembros):
        return str(red)
    return None


CLASIFICADORES: Dict[str, Type[Clasificador]] = {c.nombre: c for c in (SinClasificar, PorPolitica, PorDestino)}


def crear(nombre: str, politicas) -> Clasificador:
    if nombre not in CLASIFICADORES:
        raise ValueError(f"clasificador desconocido: {nombre} (hay: {', '.join(CLASIFICADORES)})")
    return CLASIFICADORES[nombre](politicas)
