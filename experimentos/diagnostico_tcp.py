#!/usr/bin/env python3
"""
Diagnóstico de TCP en los enlaces de acceso (historia PCIII-14).

Lo que ya se sabe (corridas del 23/10/2026 en la VM):
  - Con la ráfaga que pone Open vSwitch (1500 B) el enlace entrega ~83 %, incluso
    con UDP: en la VM el reloj que reactiva a HTB llega tarde.
  - Open vSwitch no deja fijar la ráfaga de la clase raíz (1:fffe) y la vuelve a
    1500 B con cualquier cambio en su base de datos. El gestor de colas ahora la
    refuerza con tc tras cada escritura (controlador/colas.py, reforzar_raiz).
  - Una fila corta (pfifo:64) baja el ping bajo carga de ~600 ms a ~67 ms.

Esta corrida verifica la solución: con ráfaga de 20 ms en colas y raíz, el
enlace debe llegar al 95 % o más, también después de un cambio en caliente.

Para cada configuración mide en la Sala elegida:
  - TCP bajada y TCP subida: Mbps de la aplicación y del enlace (contadores HTB)
  - UDP bajada a ritmo fijo, por encima de la capacidad: muestra cuánto entrega
    el limitador por sí solo, sin depender de TCP
  - ping sin clasificar (va por la misma cola que la carga)

Uso (Ryu corriendo en otra terminal):
  sudo python3 experimentos/diagnostico_tcp.py              # Sala 1, ~6 min
Resultados: experimentos/resultados/diagnostico_tcp.csv
"""
import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
import time

import yaml
from mininet.log import info, setLogLevel

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "topologia"))
sys.path.insert(0, AQUI)

from empresa_xyz import AVISO_RYU, CONFIG_DEFECTO, EmpresaXYZ, controlador_activo  # noqa: E402
from controlador.colas import ErrorColas  # noqa: E402
import medicion as m  # noqa: E402

CSV = os.path.join(AQUI, "resultados", "diagnostico_tcp.csv")
CAMPOS = ["fecha", "sala", "configuracion", "estrategia", "hoja", "rafaga_ms",
          "rafaga_raiz_bytes", "prueba", "capacidad_mbps", "app_mbps", "enlace_mbps",
          "uso_app_pct", "uso_enlace_pct", "ping_ms", "ping_p95_ms", "ping_perdida_pct"]
# (nombre, estrategia, fila de espera, ráfaga en ms para colas Y raíz (0 = la de OVS),
#  cambio en caliente en otro enlace antes de medir)
PRUEBAS = [
    ("base_fifo_raf0",       "sin_qos", "fifo",     0,  False),
    ("base_fifo_raf20",      "sin_qos", "fifo",     20, False),
    ("colas_p64_raf0",       "colas",   "pfifo:64", 0,  False),
    ("colas_p64_raf20",      "colas",   "pfifo:64", 20, False),
    ("colas_p64_raf20_camb", "colas",   "pfifo:64", 20, True),
]


def aplicar(emp, estrategia, hoja, rafaga_ms, cambio, sala):
    """Aplica la QoS a todos los enlaces. El gestor ya refuerza la ráfaga de la raíz."""
    emp.colas.hoja, emp.colas.burst_ms = hoja, rafaga_ms
    for _, puerto, mbps, _ in emp.puertos_acceso:
        if estrategia == "colas":
            emp.colas.aplicar(puerto, mbps)
        else:
            emp.colas.linea_base(puerto, mbps)
    if cambio:   # como hará el motor: cambiar una cola de otro enlace en caliente
        otro = next(p for sw, p, _, s in emp.puertos_acceso if sw != f"acc{sala}" and s == "bajada")
        emp.colas.cambiar(otro, "restringido", max_rate=1_000_000)


def medir(emp, prueba, origen, destino, cuello, duracion, puerto, s, capacidad):
    net = emp.net
    o, d = net.get(origen), net.get(destino)
    if prueba.startswith("tcp"):
        rx, ruta = m.receptor_tcp(d, puerto, duracion + 40)
        time.sleep(1)
        tx = m.emisor_tcp(o, d.IP(), puerto, duracion)
    else:   # UDP a 1.2 veces la capacidad: el limitador queda siempre con trabajo
        d.cmd(f"iperf3 -s -1 -p {puerto} -D")
        time.sleep(1)
        tx = o.popen(["iperf3", "-c", d.IP(), "-p", str(puerto), "-u", "-l", "1400",
                      "-b", f"{capacidad * 1.2:.0f}M", "-t", str(duracion), "-J"],
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    time.sleep(4)
    b0, t0 = emp.colas.bytes_enviados(cuello), time.time()
    ping = m.sonda_ping(net.get(f"{s}tel"), net.get("ofpbx").IP(), duracion - 6, intervalo=0.2)
    r_ping = m.resultado_ping(m.leer(ping))
    b1, t1 = emp.colas.bytes_enviados(cuello), time.time()
    enlace = round((b1 - b0) * 8 / (t1 - t0) / 1e6, 2)
    if prueba.startswith("tcp"):
        m.esperar(tx, limite=duracion + 20)
        m.esperar(rx, limite=20)
        app = m.resultado_tcp(ruta).get("mbps", 0.0)
    else:
        try:
            fin = json.loads(m.leer(tx))["end"]["sum"]
            app = round(fin["bits_per_second"] * (1 - fin["lost_percent"] / 100) / 1e6, 2)
        except (ValueError, KeyError):
            app = 0.0
    return app, enlace, r_ping


def guardar(filas):
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    nuevo = not os.path.exists(CSV)
    with open(CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def main():
    p = argparse.ArgumentParser(description="Diagnóstico de TCP en los enlaces de acceso")
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
    capacidad = next(x["enlace"]["mbps"] for x in cfg["salas"] if x["id"] == args.sala)
    s = f"sa{args.sala}"
    emp = EmpresaXYZ(cfg, controlador=not args.sin_controlador)
    emp.construir()
    emp.net.start()
    filas, saltadas = [], []
    fecha = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        emp.configurar()
        cuellos = {sentido: p for sw, p, _, sentido in emp.puertos_acceso if sw == f"acc{args.sala}"}
        info("*** Esperando 5 s a que la red se estabilice\n")
        time.sleep(5)
        for a, b in ((f"{s}cli1", "inetupd"), (f"{s}srv", "ofbak"), (f"{s}tel", "ofpbx")):
            emp.net.get(a).cmd(f"ping -c2 -W2 {emp.net.get(b).IP()}")

        pruebas = (("tcp_bajada", "inetupd", f"{s}cli1", "bajada", 5401),
                   ("tcp_subida", f"{s}srv", "ofbak", "subida", 5402),
                   ("udp_bajada", "inetupd", f"{s}cli1", "bajada", 5403))
        n = len(PRUEBAS)
        info(f"\n*** {n} configuraciones x {len(pruebas)} pruebas x {args.duracion} s "
             f"(unos {n * len(pruebas) * (args.duracion + 5) // 60 + 1} min)\n")
        for k, (nombre, estrategia, hoja, rafaga, cambio) in enumerate(PRUEBAS, 1):
            try:
                aplicar(emp, estrategia, hoja, rafaga, cambio, args.sala)
            except ErrorColas as e:
                primera = str(e).splitlines()[-1]
                info(f"    [{k}/{n}] {nombre}: se salta ({primera})\n")
                saltadas.append((nombre, primera))
                continue
            time.sleep(1)
            raiz = emp.colas.rafaga_raiz(cuellos["bajada"])
            for prueba, origen, destino, sentido, puerto in pruebas:
                app, enlace, pg = medir(emp, prueba, origen, destino, cuellos[sentido],
                                        args.duracion, puerto, s, capacidad)
                fila = {"fecha": fecha, "sala": args.sala, "configuracion": nombre,
                        "estrategia": estrategia, "hoja": hoja, "rafaga_ms": rafaga,
                        "rafaga_raiz_bytes": raiz, "prueba": prueba,
                        "capacidad_mbps": capacidad, "app_mbps": app, "enlace_mbps": enlace,
                        "uso_app_pct": round(100 * app / capacidad, 1),
                        "uso_enlace_pct": round(100 * enlace / capacidad, 1),
                        "ping_ms": pg["rtt_ms"], "ping_p95_ms": pg["rtt_p95_ms"],
                        "ping_perdida_pct": pg["perdida_pct"]}
                filas.append(fila)
                info(f"    [{k}/{n}] {nombre:20s} {prueba:10s} app {fila['uso_app_pct']:5.1f} %  "
                     f"enlace {fila['uso_enlace_pct']:5.1f} %  ping {pg['rtt_ms']} ms\n")
    finally:
        emp.limpiar()
        emp.net.stop()
        if filas:       # se guarda lo medido aunque algo falle a mitad de camino
            guardar(filas)

    if filas:
        resumen(filas)
        info(f"\n*** Resultados agregados a {CSV}\n")
    for nombre, motivo in saltadas:
        info(f"*** Se saltó {nombre}: {motivo}\n")


def resumen(filas):
    info(f"\n    {'Configuración':20s} {'Raíz':>7s} {'TCP baj':>8s} {'TCP sub':>8s} {'UDP baj':>8s} "
         f"{'Ping':>8s} {'Ping p95':>9s}\n")
    grupos = {}
    for f in filas:
        grupos.setdefault(f["configuracion"], {})[f["prueba"]] = f
    for nombre, g in grupos.items():
        tb, ts, ub = (g.get(x, {}) for x in ("tcp_bajada", "tcp_subida", "udp_bajada"))
        pings = [x["ping_ms"] for x in (tb, ts) if x.get("ping_ms") is not None]
        p95 = [x["ping_p95_ms"] for x in (tb, ts) if x.get("ping_p95_ms") is not None]
        raiz = tb.get("rafaga_raiz_bytes") or 0
        info(f"    {nombre:20s} {raiz:>6} B {tb.get('uso_enlace_pct', 0):>6.1f} % "
             f"{ts.get('uso_enlace_pct', 0):>6.1f} % {ub.get('uso_enlace_pct', 0):>6.1f} % "
             f"{(sum(pings) / len(pings)) if pings else 0:>5.1f} ms {max(p95) if p95 else 0:>6.1f} ms\n")
    info("    Porcentajes = uso real del enlace (contadores de HTB). Raíz = ráfaga de la clase 1:fffe.\n")


if __name__ == "__main__":
    main()
