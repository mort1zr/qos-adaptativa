"""
Condiciones del enlace del operador (punto 2 de las mejoras de evidencia).

Un enlace real no siempre entrega lo contratado: el operador puede tener más
retardo, perder paquetes o, por una falla o una congestión en su red, entregar
menos capacidad (por ejemplo, la mitad mientras dura un incidente). Lo
importante es DÓNDE ocurre: en la red del operador, DESPUÉS de nuestras colas.
Si el enlace entrega menos de lo que nuestras colas creen, la fila se forma en
el operador (una FIFO grande que no prioriza nada) y los carriles dejan de
proteger a la voz. Una estrategia fija no se entera; una dinámica puede verlo
en la telemetría y bajar sus tasas por debajo de lo que el enlace entrega de
verdad (lo que hacen los routers con "SQM autorate" en enlaces 4G o de cable).

Dónde se aplica, en el router del operador (rop):
  bajada (operador -> sede): netem en la salida rop-s<sede>, que ya tenía el
         retardo base del enlace; queda ANTES de las colas de bajada de la sede,
         como el equipo del operador que entrega el tráfico.
  subida (sede -> operador): netem en una interfaz IFB que recibe lo que entra
         por rop-s<sede>; queda DESPUÉS de las colas de subida de la sede.

Condiciones de una fase (escenarios.yaml, clave 'enlace'):
  capacidad_pct  % de la capacidad contratada que entrega el operador (100)
  perdida_pct    pérdida aleatoria del operador, en % (0)
  retardo_ms     retardo extra de un sentido, en ms (0)
  buffer_ms      cuánto guarda la fila del operador antes de descartar (250 ms,
                 un valor común en equipos de operador)

Cada cambio BORRA la qdisc y la vuelve a crear: 'tc qdisc replace ... netem' con
menos parámetros conserva los que no se nombran (por ejemplo, el límite 'rate'),
y el enlace quedaba limitado después de "recuperarse". Después de aplicar, se
verifica con 'tc qdisc show' que el límite esté (o no esté) donde corresponde.

Decisiones de realismo (declaradas en la tesis):
  - Sin "jitter" artificial: netem lo crea reordenando paquetes, cosa que un
    enlace real casi no hace; la variación real del retardo viene de las filas,
    y esas ya están (las nuestras y la del operador cuando se satura).
  - Enlaces simétricos: los de una empresa con fibra dedicada o MPLS lo son;
    la asimetría es típica de enlaces residenciales.
"""
from typing import Callable, Dict, Optional

CLAVES = {"capacidad_pct": (1, 100), "perdida_pct": (0, 50), "retardo_ms": (0, 1000), "buffer_ms": (10, 5000)}
NORMAL = {"capacidad_pct": 100, "perdida_pct": 0, "retardo_ms": 0, "buffer_ms": 250}


def validar(enlace: Optional[dict]) -> list:
    """Errores de las condiciones de una fase (lista vacía si están bien)."""
    errores = []
    for k, v in (enlace or {}).items():
        if k not in CLAVES:
            errores.append(f"condición de enlace desconocida '{k}' (hay: {', '.join(CLAVES)})")
        elif not isinstance(v, (int, float)) or not CLAVES[k][0] <= v <= CLAVES[k][1]:
            errores.append(f"'{k}' debe estar entre {CLAVES[k][0]} y {CLAVES[k][1]}")
    return errores


def condiciones(enlace: Optional[dict]) -> dict:
    return {**NORMAL, **(enlace or {})}


def args_netem(retardo_ms: float, c: dict, mbps: float) -> str:
    """Parámetros de netem para un sentido. Sin degradación, solo el retardo."""
    partes = []
    if retardo_ms > 0:
        partes.append(f"delay {retardo_ms:g}ms")
    if c["perdida_pct"] > 0:
        partes.append(f"loss {c['perdida_pct']:g}%")
    if c["capacidad_pct"] < 100:
        tasa = mbps * c["capacidad_pct"] / 100
        paquetes = max(10, int(tasa * 1e6 * c["buffer_ms"] / 1000 / (1500 * 8)))
        partes.append(f"rate {tasa:g}mbit limit {paquetes}")
    return " ".join(partes)


class Operador:
    """Aplica las condiciones del operador al enlace de una sede."""

    def __init__(self, rop, retardos: Dict[int, float], capacidades: Dict[int, float],
                 avisar: Callable = print):
        self.rop, self.retardos, self.capacidades, self.avisar = rop, retardos, capacidades, avisar
        self._ifb = set()
        self.actual: Dict[int, dict] = {}

    @classmethod
    def de_empresa(cls, emp, avisar: Callable = print) -> "Operador":
        retardos = {int(intf.rsplit("s", 1)[1]): ms for r, intf, ms in emp.retardos
                    if r.name == "rop" and intf.startswith("rop-s")}
        capacidades = {datos["sede_id"]: datos["mbps"] for datos in emp.acc.values()}
        return cls(emp.routers["rop"], retardos, capacidades, avisar)

    def _cmd(self, texto: str) -> str:
        salida = self.rop.cmd(texto + " 2>&1")
        if salida.strip():
            raise RuntimeError(f"operador: '{texto}' falló: {salida.strip()}")
        return salida

    def _poner(self, intf: str, args: str):
        """Deja 'intf' con netem 'args' (o sin qdisc propia si args está vacío), desde cero."""
        self.rop.cmd(f"tc qdisc del dev {intf} root 2>/dev/null")
        if args:
            self._cmd(f"tc qdisc add dev {intf} root netem {args}")

    def _verificar(self, intf: str, args: str):
        mostrado = self.rop.cmd(f"tc qdisc show dev {intf} root")
        tiene_rate = " rate " in f" {mostrado} "
        if tiene_rate != (" rate " in f" {args} "):
            raise RuntimeError(f"operador: {intf} quedó mal configurada: {mostrado.strip()}")

    def _asegurar_ifb(self, sede: int):
        if sede in self._ifb:
            return
        ifb, intf = f"ifb{sede}", f"rop-s{sede}"
        self._cmd(f"ip link add {ifb} type ifb")
        self._cmd(f"ip link set {ifb} up")
        self._cmd(f"tc qdisc add dev {intf} handle ffff: ingress")
        self._cmd(f"tc filter add dev {intf} parent ffff: protocol all matchall "
                  f"action mirred egress redirect dev {ifb}")
        self._ifb.add(sede)

    def aplicar(self, sede: int, enlace: Optional[dict]) -> dict:
        """Deja el enlace de la sede con esas condiciones (None = normal)."""
        c = condiciones(enlace)
        if self.actual.get(sede, NORMAL) == c:
            return c
        mbps = self.capacidades[sede]
        base = self.retardos.get(sede, 0)
        bajada = args_netem(base + c["retardo_ms"], c, mbps)
        self._poner(f"rop-s{sede}", bajada)
        self._verificar(f"rop-s{sede}", bajada)
        subida = args_netem(c["retardo_ms"], c, mbps)
        if subida or sede in self._ifb:
            self._asegurar_ifb(sede)
            self._poner(f"ifb{sede}", subida)
            self._verificar(f"ifb{sede}", subida)
        self.actual[sede] = c
        if c != NORMAL:
            self.avisar(f"    [operador] sede {sede}: entrega {c['capacidad_pct']:g} % de {mbps:g} Mbps, "
                        f"pérdida {c['perdida_pct']:g} %, +{c['retardo_ms']:g} ms")
        elif enlace is not None or sede in self.actual:
            self.avisar(f"    [operador] sede {sede}: enlace normal")
        return c

    def normalizar(self):
        for sede in list(self.actual):
            self.aplicar(sede, None)
