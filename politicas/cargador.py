#!/usr/bin/env python3
"""
Cargador y validador de las políticas de QoS (historia PCIII-10).

Uso:
  python3 politicas/cargador.py               # valida y muestra un resumen
  python3 -m unittest politicas.test_cargador # pruebas

Desde código:
  from politicas.cargador import cargar
  pol = cargar()
  pol.clasificar(segmento="wifi_clientes", tipo="cliente_wifi", servicio="streaming")
  pol.tasas(30)   # rate/ceil de cada clase para un enlace de 30 Mbps

Compatible con Python 3.9 (lo usará también el controlador Ryu).
"""
import os
import sys
from typing import Dict, Optional, Tuple

import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
POLITICAS_DEFECTO = os.path.join(AQUI, "politicas.yaml")
EMPRESA_DEFECTO = os.path.join(RAIZ, "topologia", "empresa_xyz.yaml")

SEGMENTOS_TOPOLOGIA = {"servidores", "maquinas", "administracion", "pagos", "cctv",
                       "wifi_personal", "wifi_clientes", "internet"}
CONDICIONES = {"segmento", "tipo", "servicio"}
OBJETIVOS_REQUERIDOS = {"jitter_ms", "perdida_pct", "latencia_p95_ms", "mos_min"}
MAX_COLA = 7   # HTB en Open vSwitch admite más, pero 8 colas sobran para 6 clases


class PoliticaInvalida(ValueError):
    """Se lanza con la lista completa de problemas encontrados."""

    def __init__(self, errores):
        self.errores = errores
        super().__init__("Políticas inválidas:\n  - " + "\n  - ".join(errores))


def _lista(valor):
    if valor is None:
        return None
    return list(valor) if isinstance(valor, (list, tuple, set)) else [valor]


def vocabulario_empresa(ruta=EMPRESA_DEFECTO):
    """Tipos de equipo y servicios que existen en la topología."""
    with open(ruta) as f:
        emp = yaml.safe_load(f)
    tipos = set()
    for equipos in emp["oficina"]["segmentos"].values():
        tipos.update(t for _, t in equipos)
    tipos.update(t for _, t in emp["plantilla_sala"]["administracion"])
    tipos.update({"servidor_sala", "tragamonedas", "derby", "ruleta", "pos", "nvr",
                  "camara_ip", "celular", "cliente_wifi"})
    servicios = {s["servicio"] for s in emp["internet"]["servidores"]}
    return tipos, servicios


class Politicas:
    def __init__(self, datos: dict, vocabulario: Optional[Tuple[set, set]] = None):
        self.datos = datos
        self._validar(vocabulario)
        self.objetivos = dict(datos["objetivos"])
        self.clases = sorted(datos["clases"], key=lambda c: c["prioridad"])
        self.por_nombre = {c["nombre"]: c for c in self.clases}
        self.reglas = datos.get("reglas", [])
        self.defecto = datos["servicios_por_defecto"]
        self.servicios_internos = datos.get("servicios_internos", {})
        self.motor = datos.get("motor", {})

    # ---------------- validación ----------------
    def _validar(self, vocabulario):
        d, errores = self.datos, []
        for clave in ("objetivos", "clases", "servicios_por_defecto"):
            if clave not in d:
                errores.append(f"falta la sección '{clave}'")
        if errores:
            raise PoliticaInvalida(errores)

        faltan = OBJETIVOS_REQUERIDOS - set(d["objetivos"])
        if faltan:
            errores.append(f"objetivos sin definir: {', '.join(sorted(faltan))}")
        for k, v in d["objetivos"].items():
            if not isinstance(v, (int, float)) or v <= 0:
                errores.append(f"el objetivo '{k}' debe ser un número positivo")

        nombres, prioridades, colas, suma = set(), set(), {}, 0.0
        for c in d["clases"]:
            n = c.get("nombre", "?")
            if n in nombres:
                errores.append(f"clase repetida: '{n}'")
            nombres.add(n)
            if c.get("prioridad") in prioridades:
                errores.append(f"prioridad {c.get('prioridad')} repetida (clase '{n}')")
            prioridades.add(c.get("prioridad"))
            q = c.get("cola")
            if not isinstance(q, int) or isinstance(q, bool) or not 0 <= q <= MAX_COLA:
                errores.append(f"clase '{n}': cola debe ser un entero entre 0 y {MAX_COLA}")
            elif q in colas:
                errores.append(f"cola {q} repetida (clases '{colas[q]}' y '{n}')")
            else:
                colas[q] = n
            g, t = c.get("garantia_pct"), c.get("techo_pct")
            if not isinstance(g, (int, float)) or g <= 0:
                errores.append(f"clase '{n}': garantia_pct debe ser mayor que 0 (HTB lo exige)")
                g = 0
            if not isinstance(t, (int, float)) or not (0 < t <= 100):
                errores.append(f"clase '{n}': techo_pct debe estar entre 1 y 100")
            elif t < g:
                errores.append(f"clase '{n}': el techo ({t} %) es menor que la garantía ({g} %)")
            suma += g
        if suma > 100:
            errores.append(f"la suma de garantías es {suma:g} %: no puede pasar de 100 %")

        servicios_conocidos = set(d["servicios_por_defecto"])
        for s, clase in d["servicios_por_defecto"].items():
            if clase not in nombres:
                errores.append(f"servicio '{s}' apunta a una clase inexistente: '{clase}'")
        if "desconocido" not in d["servicios_por_defecto"]:
            errores.append("servicios_por_defecto debe incluir 'desconocido'")
        elif colas and colas.get(0) != d["servicios_por_defecto"]["desconocido"]:
            errores.append(f"la cola 0 recibe el tráfico no clasificado: debe ser la clase de "
                           f"'desconocido' ('{d['servicios_por_defecto']['desconocido']}'), "
                           f"no '{colas.get(0, 'ninguna')}'")
        for tipo, s in (d.get("servicios_internos") or {}).items():
            if s not in servicios_conocidos:
                errores.append(f"servicios_internos: '{tipo}' usa un servicio sin clase por defecto: '{s}'")

        tipos_ok, servicios_topo = vocabulario if vocabulario else (None, None)
        if servicios_topo:
            for s in sorted(servicios_topo - servicios_conocidos):
                errores.append(f"el servicio de Internet '{s}' no tiene clase en servicios_por_defecto")

        for i, r in enumerate(d.get("reglas") or [], 1):
            n = r.get("nombre", f"regla {i}")
            if r.get("clase") not in nombres:
                errores.append(f"regla '{n}': clase inexistente '{r.get('clase')}'")
            if not CONDICIONES & set(r):
                errores.append(f"regla '{n}': necesita al menos una condición (segmento, tipo o servicio)")
            for seg in _lista(r.get("segmento")) or []:
                if seg not in SEGMENTOS_TOPOLOGIA:
                    errores.append(f"regla '{n}': segmento desconocido '{seg}'")
            for srv in _lista(r.get("servicio")) or []:
                if srv not in servicios_conocidos:
                    errores.append(f"regla '{n}': servicio desconocido '{srv}'")
            if tipos_ok:
                for t in _lista(r.get("tipo")) or []:
                    if t not in tipos_ok:
                        errores.append(f"regla '{n}': tipo de equipo desconocido '{t}'")

        for c in (d.get("motor") or {}).get("clases_protegidas", []):
            if c not in nombres:
                errores.append(f"motor.clases_protegidas: clase inexistente '{c}'")
        if errores:
            raise PoliticaInvalida(errores)

    # ---------------- uso ----------------
    def clasificar(self, segmento: str, tipo: str, servicio: str) -> Tuple[str, str]:
        """Devuelve (clase, motivo) para un flujo según su origen y su servicio."""
        for r in self.reglas:
            if all(_coincide(r.get(k), v) for k, v in
                   (("segmento", segmento), ("tipo", tipo), ("servicio", servicio))):
                return r["clase"], r["nombre"]
        if servicio in self.defecto:
            return self.defecto[servicio], f"servicio '{servicio}' por defecto"
        return self.defecto["desconocido"], "servicio desconocido"

    def servicio_de(self, destino: dict) -> str:
        """Servicio que ofrece un equipo destino (fila del inventario)."""
        if destino.get("segmento") == "internet":
            return destino.get("tipo", "desconocido")
        return self.servicios_internos.get(destino.get("tipo"), "desconocido")

    def tasas(self, mbps: float) -> Dict[str, Tuple[int, int]]:
        """rate y ceil (bits/s) de cada clase para un enlace de 'mbps'."""
        bps = mbps * 1_000_000
        return {c["nombre"]: (int(bps * c["garantia_pct"] / 100), int(bps * c["techo_pct"] / 100))
                for c in self.clases}

    def cola(self, clase: str) -> int:
        """Número de cola de Open vSwitch de una clase (para set_queue)."""
        return self.por_nombre[clase]["cola"]

    def clase_de_cola(self, cola: int) -> str:
        for c in self.clases:
            if c["cola"] == cola:
                return c["nombre"]
        raise KeyError(f"no hay clase en la cola {cola}")


def _coincide(condicion, valor) -> bool:
    return condicion is None or valor in _lista(condicion)


def cargar(ruta: str = POLITICAS_DEFECTO, empresa: Optional[str] = EMPRESA_DEFECTO) -> Politicas:
    with open(ruta) as f:
        datos = yaml.safe_load(f)
    vocab = vocabulario_empresa(empresa) if empresa and os.path.exists(empresa) else None
    return Politicas(datos, vocab)


def main():
    try:
        pol = cargar(sys.argv[1] if len(sys.argv) > 1 else POLITICAS_DEFECTO)
    except PoliticaInvalida as e:
        sys.exit(str(e))
    o = pol.objetivos
    print(f"Políticas válidas. Objetivos: jitter < {o['jitter_ms']} ms, pérdida < {o['perdida_pct']} %, "
          f"latencia p95 < {o['latencia_p95_ms']} ms, MOS >= {o['mos_min']}\n")
    print(f"  {'Clase':12s} {'Cola':>4s} {'Prio':>4s} {'Garantía':>9s} {'Techo':>6s}   "
          f"10 Mbps (rate/ceil)   30 Mbps (rate/ceil)")
    t10, t30 = pol.tasas(10), pol.tasas(30)
    for c in pol.clases:
        n = c["nombre"]
        print(f"  {n:12s} {c['cola']:>4d} {c['prioridad']:>4d} {c['garantia_pct']:>8g}% {c['techo_pct']:>5g}%   "
              f"{t10[n][0] / 1e6:5.1f} / {t10[n][1] / 1e6:5.1f} Mbps     {t30[n][0] / 1e6:5.1f} / {t30[n][1] / 1e6:5.1f} Mbps")
    print("\n  Ejemplos de clasificación:")
    ejemplos = [
        ("tragamonedas", "maquinas", "gestion"),
        ("pos", "pagos", "pagos"),
        ("telefono_ip", "administracion", "voip"),
        ("pc_musica", "administracion", "streaming"),
        ("cliente_wifi", "wifi_clientes", "streaming"),
        ("cliente_wifi", "wifi_clientes", "voip"),
        ("pc_sistemas", "administracion", "ia_generativa"),
        ("pc_contabilidad", "administracion", "ia_generativa"),
        ("pc_monitoreo", "administracion", "cctv"),
        ("servidor_sala", "maquinas", "respaldo"),
    ]
    for tipo, seg, srv in ejemplos:
        clase, motivo = pol.clasificar(seg, tipo, srv)
        print(f"    {tipo:16s} -> {srv:14s} = {clase:12s} ({motivo})")


if __name__ == "__main__":
    main()
