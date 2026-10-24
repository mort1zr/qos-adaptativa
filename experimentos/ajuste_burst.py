#!/usr/bin/env python3
"""
Ajuste de la ráfaga (burst) de HTB (historia PCIII-14).

En el Sprint 1, una descarga TCP solo usaba unos 22 de los 30 Mbps de la
Sala 1. Este script levanta la red UNA vez y mide una descarga TCP (bajada) y
un respaldo TCP (subida) con varias configuraciones de cola, cambiando solo la
QoS de los enlaces entre una medición y otra:

  - sin_qos con la ráfaga de Open vSwitch (como en el Sprint 1)
  - colas con ráfagas de 0 (la de OVS), 2, 5, 10, 20 y 50 ms
  - las mismas sin "offloads" de las tarjetas virtuales (TSO/GSO/GRO), por
    si lo que frena a TCP son los paquetes gigantes que arman esas funciones

Mientras corre cada descarga también mide el ping (para ver si una ráfaga
mayor empeora el retardo). El objetivo es TCP al 90 % o más del enlace.

Uso (Ryu corriendo en otra terminal):
  sudo python3 experimentos/ajuste_burst.py                 # Sala 1, ~6 min
  sudo python3 experimentos/ajuste_burst.py --sala 4 --duracion 10
Resultados: experimentos/resultados/ajuste_burst.csv
"""
import argparse
import csv
import datetime
import os
import sys
import time

import yaml
from mininet.log import info, setLogLevel

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "topologia"))
sys.path.insert(0, AQUI)

from empresa_xyz import AVISO_RYU, CONFIG_DEFECTO, EmpresaXYZ, controlador_activo, sh  # noqa: E402
import medicion as m  # noqa: E402

CSV = os.path.join(AQUI, "resultados", "ajuste_burst.csv")
CAMPOS = ["fecha", "sala", "estrategia", "burst_ms", "offloads", "sentido",
          "capacidad_mbps", "mbps", "uso_pct", "rtt_ms", "rtt_p95_ms"]
OBJETIVO_PCT = 90
# (estrategia, ráfaga en ms, offloads)
PRUEBAS = [("sin_qos", 0, "si"), ("colas", 0, "si"), ("colas", 2, "si"),
           ("colas", 5, "si"), ("colas", 10, "si"), ("colas", 20, "si"),
           ("colas", 50, "si"),
           ("sin_qos", 0, "no"), ("colas", 0, "no"), ("colas", 10, "no")]


def interfaces_del_camino(emp, sala):
    """Interfaces de los equipos por donde pasan las pruebas, y puertos de acceso."""
    nodos = [f"sa{sala}cli1", f"sa{sala}srv", f"sa{sala}tel", "inetupd", "ofbak",
             "ofpbx", "rop", "r0", f"r{sala}"]
    en_hosts = [(emp.net.get(n), i.name) for n in nodos for i in emp.net.get(n).intfList()
                if i.name != "lo"]
    en_switches = [p for sw, p, _, _ in emp.puertos_acceso if sw in ("acc0", f"acc{sala}")]
    return en_hosts, en_switches


def offloads(emp, sala, activar):
    estado = "on" if activar else "off"
    en_hosts, en_switches = interfaces_del_camino(emp, sala)
    for nodo, intf in en_hosts:
        nodo.cmd(f"ethtool -K {intf} tso {estado} gso {estado} gro {estado} 2>/dev/null")
    for intf in en_switches:
        sh(f"ethtool -K {intf} tso {estado} gso {estado} gro {estado} 2>/dev/null")


def aplicar_qos(emp, estrategia, burst_ms):
    emp.colas.burst_ms = burst_ms
    for _, puerto, mbps, _ in emp.puertos_acceso:
        if estrategia == "colas":
            emp.colas.aplicar(puerto, mbps)
        else:
            emp.colas.linea_base(puerto, mbps)


def medir_tcp(emp, origen, destino, ping_de, ping_a, duracion, puerto):
    net = emp.net
    o, d = net.get(origen), net.get(destino)
    rx, ruta = m.receptor_tcp(d, puerto, duracion + 40)
    time.sleep(1)
    tx = m.emisor_tcp(o, d.IP(), puerto, duracion)
    time.sleep(3)                              # que TCP salga del arranque lento
    ping = m.sonda_ping(net.get(ping_de), net.get(ping_a).IP(), duracion - 4, intervalo=0.2)
    rtt = m.resultado_ping(m.leer(ping))
    m.esperar(tx, limite=duracion + 20)
    m.esperar(rx, limite=20)
    return m.resultado_tcp(ruta).get("mbps", 0.0), rtt


def main():
    p = argparse.ArgumentParser(description="Ajuste de la ráfaga HTB para TCP")
    p.add_argument("--sala", type=int, default=1, choices=[1, 2, 3, 4])
    p.add_argument("--duracion", type=int, default=15, help="segundos por medición")
    p.add_argument("--sin-controlador", action="store_true")
    args = p.parse_args()
    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo")
    if not args.sin_controlador and not controlador_activo():
        sys.exit(AVISO_RYU.format(ip="127.0.0.1", puerto=6633))

    setLogLevel("info")
    with open(CONFIG_DEFECTO) as f:
        cfg = yaml.safe_load(f)
    capacidad = next(s["enlace"]["mbps"] for s in cfg["salas"] if s["id"] == args.sala)
    s = f"sa{args.sala}"
    emp = EmpresaXYZ(cfg, controlador=not args.sin_controlador)
    emp.construir()
    emp.net.start()
    filas, fecha = [], datetime.datetime.now().isoformat(timespec="seconds")
    try:
        emp.configurar()
        info("*** Esperando 5 s a que la red se estabilice\n")
        time.sleep(5)
        for a, b in ((f"{s}cli1", "inetupd"), (f"{s}srv", "ofbak"), (f"{s}tel", "ofpbx")):
            emp.net.get(a).cmd(f"ping -c2 -W2 {emp.net.get(b).IP()}")

        n = len(PRUEBAS)
        info(f"\n*** {n} configuraciones x 2 sentidos x {args.duracion} s "
             f"(unos {n * 2 * (args.duracion + 8) // 60 + 1} min)\n")
        for k, (estrategia, burst, off) in enumerate(PRUEBAS, 1):
            offloads(emp, args.sala, off == "si")
            aplicar_qos(emp, estrategia, burst)
            time.sleep(1)
            for sentido, origen, destino, puerto in (
                    ("bajada", "inetupd", f"{s}cli1", 5301),
                    ("subida", f"{s}srv", "ofbak", 5302)):
                mbps, rtt = medir_tcp(emp, origen, destino, f"{s}tel", "ofpbx",
                                      args.duracion, puerto)
                fila = {"fecha": fecha, "sala": args.sala, "estrategia": estrategia,
                        "burst_ms": burst, "offloads": off, "sentido": sentido,
                        "capacidad_mbps": capacidad, "mbps": mbps,
                        "uso_pct": round(100 * mbps / capacidad, 1),
                        "rtt_ms": rtt["rtt_ms"], "rtt_p95_ms": rtt["rtt_p95_ms"]}
                filas.append(fila)
                info(f"    [{k:2d}/{n}] {estrategia:7s} ráfaga {burst:>2} ms  offloads {off:2s}  "
                     f"{sentido:6s} {mbps:6.2f} Mbps ({fila['uso_pct']:5.1f} %)  "
                     f"ping {fila['rtt_ms']} ms\n")
    finally:
        emp.limpiar()
        emp.net.stop()

    if filas:
        os.makedirs(os.path.dirname(CSV), exist_ok=True)
        nuevo = not os.path.exists(CSV)
        with open(CSV, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS)
            if nuevo:
                w.writeheader()
            w.writerows(filas)
        resumen(filas)
        info(f"\n*** Resultados agregados a {CSV}\n")


def resumen(filas):
    info(f"\n    {'Estrategia':10s} {'Ráfaga':>7s} {'Offloads':>8s} {'Bajada':>8s} {'Subida':>8s}  "
         f"{'Ping':>7s}  ¿≥{OBJETIVO_PCT} %?\n")
    grupos = {}
    for f in filas:
        grupos.setdefault((f["estrategia"], f["burst_ms"], f["offloads"]), {})[f["sentido"]] = f
    ok = []
    for (est, burst, off), g in grupos.items():
        baj, sub = g.get("bajada", {}), g.get("subida", {})
        cumple = min(baj.get("uso_pct", 0), sub.get("uso_pct", 0)) >= OBJETIVO_PCT
        if cumple and est == "colas":
            ok.append((burst, off))
        info(f"    {est:10s} {burst:>4} ms {off:>8s} {baj.get('uso_pct', 0):>6.1f} % "
             f"{sub.get('uso_pct', 0):>6.1f} %  {baj.get('rtt_ms') or '-':>5} ms  "
             f"{'sí' if cumple else 'no'}\n")
    if ok:
        burst, off = min(ok, key=lambda x: (x[1] != "si", x[0]))
        info(f"\n*** Menor ráfaga que llega al {OBJETIVO_PCT} %: {burst} ms "
             f"(offloads {off}). Pásale la tabla a Claude para fijarla.\n")
    else:
        info(f"\n*** Ninguna configuración con colas llegó al {OBJETIVO_PCT} %. "
             f"Pásale la tabla a Claude para analizarla.\n")


if __name__ == "__main__":
    main()
