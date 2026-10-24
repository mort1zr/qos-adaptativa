#!/usr/bin/env python3
"""
Colas HTB por clase en los enlaces de acceso (historia PCIII-14).

Crea, lee y cambia las colas de Open vSwitch por OVSDB (con ovs-vsctl). Lo usa
la topología al arrancar y, más adelante, el motor de decisión para mover la
garantía (min-rate) o el techo (max-rate) de una clase sin cortar el tráfico.

Lo que Open vSwitch arma en Linux en cada puerto de acceso:

    qdisc htb 1:   (lo que no tiene cola asignada va a 1:1 = cola 0)
     └─ 1:fffe      rate = ceil = capacidad del enlace
         ├─ 1:1     cola 0  masivo        (por defecto)
         ├─ 1:2     cola 1  tiempo_real
         ├─ 1:3     cola 2  critico
         └─ ...     una clase HTB por cada clase de politicas.yaml

Cada cola recibe:
  min-rate  = garantía de la clase (nadie se la puede quitar)
  max-rate  = techo de la clase (hasta dónde puede pedir prestado)
  priority  = prioridad de la clase (quién toma primero lo que sobra)
  burst     = ráfaga, en bits (ver BURST_MS_DEFECTO)

Uso desde la terminal (con la topología levantada, en otra terminal):
  sudo python3 controlador/colas.py ver acc1-eth1
  sudo python3 controlador/colas.py cambiar acc1-eth1 masivo --techo-mbps 10

Compatible con Python 3.9 (lo usará también el controlador Ryu).
"""
import argparse
import os
import subprocess
import sys
from typing import Callable, Dict, List, Optional

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from politicas.cargador import Politicas, cargar  # noqa: E402

# Ráfaga (burst) en milisegundos de la tasa, para las colas Y para la clase
# raíz del enlace. 0 = la que pone Open vSwitch (un solo paquete, 1500 B).
#
# Por qué 20 ms (experimentos/diagnostico_tcp.py en la VM, 23/10/2026): con la
# ráfaga de OVS el enlace solo entrega ~83 % de su capacidad, incluso con UDP.
# En una VM el reloj que reactiva a HTB llega tarde, y con un balde de un
# paquete cada atraso es tiempo de enlace perdido. Con 20 ms llega al 100 %.
#
# Open vSwitch no deja fijar la ráfaga de la raíz (1:fffe) y además la vuelve a
# 1500 B con CUALQUIER cambio en su base de datos, en todos los puertos. Por eso
# reforzar_raiz() la vuelve a poner con tc después de cada escritura del gestor.
# Requiere sudo (tc); sin sudo, el enlace queda en ~83 %.
BURST_MS_DEFECTO = 20
BURST_MIN_BITS = 1514 * 8       # nunca menos de un paquete completo

# Fila de espera dentro de cada cola ("hoja" de HTB). Open vSwitch no deja
# elegirla: por defecto Linux pone una FIFO de txqueuelen (1000 paquetes), que a
# 30 Mbps son ~0.4 s de espera (bufferbloat). Opciones:
#   "fifo"      la de Linux, 1000 paquetes (una red sin gestionar)
#   "pfifo:N"   FIFO de N paquetes (los routers Cisco usan 64 por clase)
#   "fq_codel"  gestión activa de cola (AQM), como el SQM de los routers modernos
# Medido en la VM: pfifo:64 baja el ping bajo carga de ~600 ms a ~67 ms sin
# perder capacidad. Se agrega con tc después de que Open vSwitch crea las
# clases; Open vSwitch no la borra al reinstalar la QoS, por eso "fifo" la quita.
HOJA_DEFECTO = "pfifo:64"


class ErrorColas(RuntimeError):
    pass


def _ejecutar(cmd: List[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise ErrorColas(f"falló: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def _mapa(texto: str) -> Dict[str, str]:
    """Convierte '{a="1", b=uuid}' (salida de ovs-vsctl) en un diccionario."""
    texto = texto.strip()
    if texto in ("", "{}", "[]"):
        return {}
    pares = {}
    for par in texto.strip("{}").split(", "):
        clave, _, valor = par.partition("=")
        pares[clave.strip().strip('"')] = valor.strip().strip('"')
    return pares


def validar_hoja(hoja: str) -> str:
    if hoja in ("fifo", "fq_codel"):
        return hoja
    tipo, _, n = hoja.partition(":")
    if tipo == "pfifo" and n.isdigit() and int(n) >= 2:
        return hoja
    raise ErrorColas(f"fila de espera desconocida: '{hoja}' (usa fifo, pfifo:N o fq_codel)")


def comandos_hoja(puerto: str, cola: int, hoja: str) -> List[str]:
    """Comando tc que pone la fila de espera 'hoja' en la clase HTB de una cola.
    Para "fifo" quita la que hubiera, y Linux vuelve a su FIFO por defecto."""
    clase = f"1:{cola + 1:x}"               # Open vSwitch: cola N -> clase 1:(N+1), en hex
    if hoja == "fifo":
        return ["tc", "qdisc", "del", "dev", puerto, "parent", clase]
    handle = f"{(cola + 1) * 16:x}:"         # 10:, 20:, 30: ... únicos por puerto
    cmd = ["tc", "qdisc", "replace", "dev", puerto, "parent", clase, "handle", handle]
    if hoja == "fq_codel":
        return cmd + ["fq_codel"]
    return cmd + ["pfifo", "limit", hoja.partition(":")[2]]


def rafaga_bytes(bps: int, ms: float) -> int:
    return max(1514, int(bps / 8 * ms / 1000))


def comando_raiz(puerto: str, enlace_bps: int, ms: float) -> List[str]:
    """Comando tc que fija la ráfaga de la clase raíz 1:fffe (Open vSwitch no lo permite)."""
    b = str(rafaga_bytes(enlace_bps, ms))
    return ["tc", "class", "change", "dev", puerto, "parent", "1:", "classid", "1:fffe", "htb",
            "rate", f"{enlace_bps}bit", "ceil", f"{enlace_bps}bit", "burst", b, "cburst", b]


class GestorColas:
    """Maneja las colas HTB de los puertos de Open vSwitch por OVSDB.

    db:       base de datos de Open vSwitch. None = la local (requiere sudo).
              Para el controlador sin sudo: "tcp:127.0.0.1:6640", tras
              'sudo ovs-vsctl set-manager ptcp:6640:127.0.0.1'.
    burst_ms: ráfaga de cada cola en ms de su techo (0 = la de Open vSwitch).
    hoja:     fila de espera de cada cola: "fifo", "pfifo:N" o "fq_codel".
    esperar:  False solo en pruebas sin ovs-vswitchd (agrega --no-wait).
    """

    def __init__(self, politicas: Optional[Politicas] = None, db: Optional[str] = None,
                 burst_ms: float = BURST_MS_DEFECTO, hoja: str = HOJA_DEFECTO,
                 esperar: bool = True,
                 ejecutar: Callable[[List[str]], str] = _ejecutar):
        self.pol = politicas or cargar()
        self.db = db
        self.burst_ms = burst_ms
        self.hoja = validar_hoja(hoja)
        self.esperar = esperar
        self._ejecutar = ejecutar

    # ---------------- bajo nivel ----------------
    def vsctl(self, *args: str) -> str:
        cmd = ["ovs-vsctl", "--timeout=10"]
        if self.db:
            cmd.append(f"--db={self.db}")
        if not self.esperar:
            cmd.append("--no-wait")
        return self._ejecutar(cmd + list(args))

    def _burst(self, techo_bps: int) -> Optional[int]:
        if not self.burst_ms:
            return None
        return max(BURST_MIN_BITS, int(techo_bps * self.burst_ms / 1000))

    @staticmethod
    def _cola_args(ref: str, min_bps: int, max_bps: int, prioridad: int,
                   burst: Optional[int]) -> List[str]:
        args = ["--", f"--id={ref}", "create", "queue",
                f"other-config:min-rate={min_bps}", f"other-config:max-rate={max_bps}",
                f"other-config:priority={prioridad}"]
        if burst:
            args.append(f"other-config:burst={burst}")
        return args

    def _instalar(self, puerto: str, enlace_bps: int, colas: List[dict]) -> None:
        """Reemplaza en una sola transacción la QoS del puerto (y borra la anterior)."""
        anterior = self.leer(puerto)
        refs = ",".join(f"{c['cola']}=@q{c['cola']}" for c in colas)
        args = ["--", "set", "port", puerto, "qos=@qos",
                "--", "--id=@qos", "create", "qos", "type=linux-htb",
                f"other-config:max-rate={enlace_bps}", f"queues={refs}"]
        for c in colas:
            args += self._cola_args(f"@q{c['cola']}", c["min_rate"], c["max_rate"],
                                    c["prioridad"], c["burst"])
        if anterior:   # QoS y Queue no se borran solas en OVSDB
            args += ["--", "destroy", "qos", anterior["uuid"]]
            for q in anterior["colas"].values():
                args += ["--", "destroy", "queue", q["uuid"]]
        self.vsctl(*args)
        self.reforzar_raiz()

    def reforzar_raiz(self) -> List[str]:
        """Vuelve a fijar la ráfaga de la raíz en TODOS los puertos con QoS HTB.

        Open vSwitch la deja en 1500 B cada vez que cambia algo en su base de
        datos, así que hay que llamarla después de cada escritura (el gestor ya
        lo hace en aplicar, linea_base, cambiar y quitar). Devuelve los puertos.
        """
        if not self.burst_ms:
            return []
        puertos = self.vsctl("--format=csv", "--data=bare", "--no-headings",
                             "--columns=name,qos", "find", "port", "qos!=[]")
        tasas = {}
        for linea in self.vsctl("--format=csv", "--data=bare", "--no-headings",
                                "--columns=_uuid,type,other_config", "list", "qos").splitlines():
            partes = linea.split(",", 2)
            if len(partes) == 3 and partes[1] == "linux-htb":
                cfg = dict(kv.partition("=")[::2] for kv in partes[2].split())
                if cfg.get("max-rate", "").isdigit():
                    tasas[partes[0]] = int(cfg["max-rate"])
        hechos = []
        for linea in puertos.splitlines():
            nombre, _, qos = linea.partition(",")
            if qos in tasas:
                self._ejecutar(comando_raiz(nombre, tasas[qos], self.burst_ms))
                hechos.append(nombre)
        return hechos

    def rafaga_raiz(self, puerto: str) -> Optional[int]:
        """Ráfaga actual de la clase raíz 1:fffe del puerto, en bytes (lee tc)."""
        salida = self._ejecutar(["tc", "class", "show", "dev", puerto, "classid", "1:fffe"])
        partes = salida.split()
        if "burst" not in partes:
            return None
        valor = partes[partes.index("burst") + 1].rstrip("b")
        mult = 1
        if valor[-1:] in ("K", "k"):
            valor, mult = valor[:-1], 1024
        elif valor[-1:] == "M":
            valor, mult = valor[:-1], 1024 * 1024
        return int(float(valor) * mult)

    # ---------------- lo que usan la topología y el motor ----------------
    def plan(self, mbps: float) -> List[dict]:
        """Colas que tendría un enlace de 'mbps' según las políticas."""
        tasas = self.pol.tasas(mbps)
        plan = []
        for c in sorted(self.pol.clases, key=lambda c: c["cola"]):
            rate, ceil = tasas[c["nombre"]]
            plan.append({"clase": c["nombre"], "cola": c["cola"], "prioridad": c["prioridad"],
                         "min_rate": rate, "max_rate": ceil, "burst": self._burst(ceil)})
        return plan

    def aplicar(self, puerto: str, mbps: float) -> List[dict]:
        """Instala una cola por clase en el puerto. Devuelve el plan aplicado."""
        plan = self.plan(mbps)
        self._instalar(puerto, int(mbps * 1_000_000), plan)
        self._hojas(puerto, [q["cola"] for q in plan])
        return plan

    def linea_base(self, puerto: str, mbps: float) -> None:
        """Estrategia sin_qos: una sola cola que solo limita la capacidad.
        Usa la misma ráfaga y fila de espera que las colas, para comparar en
        igualdad de condiciones."""
        bps = int(mbps * 1_000_000)
        self._instalar(puerto, bps, [{"cola": 0, "min_rate": bps, "max_rate": bps,
                                      "prioridad": 0, "burst": self._burst(bps)}])
        self._hojas(puerto, [0])

    def _hojas(self, puerto: str, colas: List[int]) -> None:
        """Pone la fila de espera elegida en cada cola (necesita sudo y tc)."""
        for cola in colas:
            try:
                self._ejecutar(comandos_hoja(puerto, cola, self.hoja))
            except ErrorColas:
                if self.hoja != "fifo":    # "fifo" quita la fila; si no había, no pasa nada
                    raise

    def bytes_enviados(self, puerto: str) -> int:
        """Bytes que salieron por el enlace (clase raíz 1:fffe de HTB)."""
        salida = self._ejecutar(["tc", "-s", "class", "show", "dev", puerto, "classid", "1:fffe"])
        for linea in salida.splitlines():
            linea = linea.strip()
            if linea.startswith("Sent "):
                return int(linea.split()[1])
        raise ErrorColas(f"no se encontró la clase 1:fffe en {puerto}")

    def leer(self, puerto: str) -> Optional[dict]:
        """Estado actual de la QoS del puerto, o None si no tiene."""
        uuid = self.vsctl("get", "port", puerto, "qos")
        if uuid in ("", "[]"):
            return None
        cfg = _mapa(self.vsctl("get", "qos", uuid, "other-config"))
        colas = {}
        for cola, q_uuid in _mapa(self.vsctl("get", "qos", uuid, "queues")).items():
            q = _mapa(self.vsctl("get", "queue", q_uuid, "other-config"))
            colas[int(cola)] = {
                "uuid": q_uuid,
                "min_rate": int(q.get("min-rate", 0)),
                "max_rate": int(q.get("max-rate", 0)),
                "prioridad": int(q.get("priority", 0)),
                "burst": int(q["burst"]) if "burst" in q else None,
            }
        return {"uuid": uuid, "max_rate": int(cfg.get("max-rate", 0)), "colas": colas}

    def cambiar(self, puerto: str, clase: str, min_rate: Optional[int] = None,
                max_rate: Optional[int] = None) -> dict:
        """Cambia la garantía y/o el techo de una clase en caliente.

        Solo modifica la fila Queue: Open vSwitch ajusta esa clase HTB con
        'tc class change', sin rehacer la qdisc, así el tráfico no se corta.
        Luego vuelve a fijar la ráfaga de la raíz, que Open vSwitch reinicia.
        """
        estado = self.leer(puerto)
        if not estado:
            raise ErrorColas(f"el puerto {puerto} no tiene colas (¿estrategia sin_qos?)")
        cola = self.pol.cola(clase)
        if cola not in estado["colas"]:
            raise ErrorColas(f"el puerto {puerto} no tiene la cola {cola} ({clase})")
        q = estado["colas"][cola]
        nuevo_min = q["min_rate"] if min_rate is None else int(min_rate)
        nuevo_max = q["max_rate"] if max_rate is None else int(max_rate)
        enlace = estado["max_rate"]
        if nuevo_min <= 0:
            raise ErrorColas("la garantía debe ser mayor que 0 (HTB lo exige)")
        if nuevo_max < nuevo_min:
            raise ErrorColas(f"el techo ({nuevo_max}) no puede ser menor que la garantía ({nuevo_min})")
        if enlace and nuevo_max > enlace:
            raise ErrorColas(f"el techo ({nuevo_max}) supera la capacidad del enlace ({enlace})")
        otras = sum(v["min_rate"] for k, v in estado["colas"].items() if k != cola)
        if enlace and otras + nuevo_min > enlace:
            raise ErrorColas(f"las garantías sumarían {otras + nuevo_min} bit/s, más que el enlace ({enlace})")
        args = ["set", "queue", q["uuid"], f"other-config:min-rate={nuevo_min}",
                f"other-config:max-rate={nuevo_max}"]
        if self.burst_ms:
            args.append(f"other-config:burst={self._burst(nuevo_max)}")
        self.vsctl(*args)
        self.reforzar_raiz()
        return {"clase": clase, "cola": cola, "min_rate": nuevo_min, "max_rate": nuevo_max}

    def quitar(self, puerto: str) -> None:
        """Deja el puerto sin QoS y borra sus filas de OVSDB."""
        estado = self.leer(puerto)
        args = ["--", "--if-exists", "clear", "port", puerto, "qos"]
        if estado:
            args += ["--", "destroy", "qos", estado["uuid"]]
            for q in estado["colas"].values():
                args += ["--", "destroy", "queue", q["uuid"]]
        self.vsctl(*args)
        self.reforzar_raiz()   # el cambio reinicia la raíz de los demás puertos


# ---------------- terminal ----------------
def _mbps(bps):
    return f"{bps / 1e6:6.2f}"


def imprimir_estado(gestor: GestorColas, puerto: str) -> None:
    e = gestor.leer(puerto)
    if not e:
        print(f"{puerto}: sin QoS")
        return
    try:
        raiz = gestor.rafaga_raiz(puerto)
        raiz = f", ráfaga de la raíz {raiz:,} B" if raiz else ""
    except (ErrorColas, OSError):
        raiz = ""      # sin sudo no se puede leer tc
    print(f"{puerto}: enlace {_mbps(e['max_rate'])} Mbps, {len(e['colas'])} colas{raiz}")
    print(f"  {'Cola':>4s}  {'Clase':12s} {'Garantía':>9s} {'Techo':>9s} {'Prio':>4s} {'Ráfaga':>10s}")
    for cola in sorted(e["colas"]):
        q = e["colas"][cola]
        try:
            clase = gestor.pol.clase_de_cola(cola) if len(e["colas"]) > 1 else "(única)"
        except KeyError:
            clase = "?"
        burst = f"{q['burst'] // 8:,} B" if q["burst"] else "OVS"
        print(f"  {cola:>4d}  {clase:12s} {_mbps(q['min_rate'])} M {_mbps(q['max_rate'])} M "
              f"{q['prioridad']:>4d} {burst:>10s}")


def main():
    p = argparse.ArgumentParser(description="Colas HTB por clase en Open vSwitch")
    p.add_argument("--db", default=None, help="por ejemplo tcp:127.0.0.1:6640")
    sub = p.add_subparsers(dest="accion", required=True)
    v = sub.add_parser("ver", help="muestra las colas de un puerto")
    v.add_argument("puerto")
    c = sub.add_parser("cambiar", help="cambia la garantía o el techo de una clase en caliente")
    c.add_argument("puerto")
    c.add_argument("clase")
    c.add_argument("--garantia-mbps", type=float)
    c.add_argument("--techo-mbps", type=float)
    pl = sub.add_parser("plan", help="muestra las colas que tendría un enlace (sin aplicar)")
    pl.add_argument("mbps", type=float)
    pl.add_argument("--burst-ms", type=float, default=BURST_MS_DEFECTO)
    args = p.parse_args()

    try:
        if args.accion == "plan":
            g = GestorColas(burst_ms=args.burst_ms)
            print(f"Enlace de {args.mbps:g} Mbps:")
            for q in g.plan(args.mbps):
                print(f"  cola {q['cola']}  {q['clase']:12s} garantía {_mbps(q['min_rate'])} Mbps  "
                      f"techo {_mbps(q['max_rate'])} Mbps  prioridad {q['prioridad']}")
            return
        g = GestorColas(db=args.db)
        if args.accion == "ver":
            imprimir_estado(g, args.puerto)
        else:
            mb = lambda x: None if x is None else int(x * 1_000_000)  # noqa: E731
            r = g.cambiar(args.puerto, args.clase, mb(args.garantia_mbps), mb(args.techo_mbps))
            print(f"Cola {r['cola']} ({r['clase']}): garantía {_mbps(r['min_rate'])} Mbps, "
                  f"techo {_mbps(r['max_rate'])} Mbps")
            imprimir_estado(g, args.puerto)
    except ErrorColas as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
