"""
Inventario de la red para el controlador (historia PCIII-16).

Lee los archivos que escribe la topología al construirse:
  topologia/inventario.csv   equipos: nombre, sede, segmento, tipo, IP, área
  topologia/switches.csv     switches: DPID, rol (acceso, segmento, isla,
                             internet) y, en los de acceso, sus puertos OpenFlow

Se recargan solos si la topología los vuelve a escribir. Compatible con
Python 3.9 (lo usa la aplicación de Ryu).
"""
import csv
import os
from typing import Dict, Optional

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVENTARIO = os.path.join(RAIZ, "topologia", "inventario.csv")
SWITCHES = os.path.join(RAIZ, "topologia", "switches.csv")


def _mtime(ruta):
    try:
        return os.path.getmtime(ruta)
    except OSError:
        return None


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


class Inventario:
    def __init__(self, inventario: str = INVENTARIO, switches: str = SWITCHES):
        self.rutas = (inventario, switches)
        self._versiones = (None, None)
        self.por_ip: Dict[str, dict] = {}
        self.por_dpid: Dict[int, dict] = {}
        self.recargar()

    def recargar(self) -> bool:
        """Vuelve a leer los archivos si cambiaron. Devuelve True si recargó."""
        versiones = tuple(_mtime(r) for r in self.rutas)
        if versiones == self._versiones:
            return False
        self._versiones = versiones
        self.por_ip, self.por_dpid = {}, {}
        if versiones[0] is not None:
            with open(self.rutas[0], newline="") as f:
                for fila in csv.DictReader(f):
                    fila["sede_id"] = _entero(fila.get("sede_id"))   # None para Internet
                    fila.setdefault("area", fila.get("segmento", ""))
                    self.por_ip[fila["ip"]] = fila
        if versiones[1] is not None:
            with open(self.rutas[1], newline="") as f:
                for fila in csv.DictReader(f):
                    for k in ("dpid", "sede_id", "puerto_operador", "puerto_sede"):
                        fila[k] = _entero(fila.get(k))
                    fila["mbps"] = float(fila["mbps"]) if fila.get("mbps") else None
                    self.por_dpid[fila["dpid"]] = fila
        return True

    def switch(self, dpid: int) -> Optional[dict]:
        return self.por_dpid.get(dpid)

    def es_acceso(self, dpid: int) -> bool:
        sw = self.por_dpid.get(dpid)
        return bool(sw and sw["tipo"] == "acceso")

    def equipo(self, ip: str) -> Optional[dict]:
        return self.por_ip.get(ip)

    def accesos(self):
        return [sw for sw in self.por_dpid.values() if sw["tipo"] == "acceso"]
