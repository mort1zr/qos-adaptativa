#!/usr/bin/env python3
"""
Prueba de congestión sin QoS en una sala (historia PCIII-13).

Levanta la topología de la Empresa XYZ y mide, con las sondas de trafico.py,
la calidad de una llamada VoIP
(teléfono de la sala -> central telefónica de la oficina) y de una videollamada
(Internet -> PC de caja) en dos fases:

  1. sin_carga:      solo las sondas.
  2. con_descargas:  3 clientes del WiFi descargan desde Internet (bajada) y el
                     servidor de sala envía un respaldo a la oficina (subida).

Uso (Ryu corriendo en otra terminal):
  sudo python3 experimentos/prueba_congestion.py
  sudo python3 experimentos/prueba_congestion.py --sala 4 --duracion 30
Resultados: experimentos/resultados/mediciones.csv
"""
import argparse
import os
import sys
import time

import yaml
from mininet.log import info, setLogLevel

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "topologia"))
sys.path.insert(0, AQUI)

from empresa_xyz import AVISO_RYU, CONFIG_DEFECTO, EmpresaXYZ, controlador_activo  # noqa: E402
import medicion as m  # noqa: E402

PUERTO_VOZ, PUERTO_VIDEO, PUERTO_BAJADA, PUERTO_SUBIDA = 5001, 5002, 5101, 5201


def equipos_necesarios(sala):
    s = f"sa{sala}"
    return [f"{s}tel", "ofpbx", f"{s}caja", "inetvc", "inetupd", f"{s}srv", "ofbak",
            f"{s}cli1", f"{s}cli2", f"{s}cli3"]


def validar(emp, sala):
    """Comprueba que los equipos de la prueba existan antes de levantar la red."""
    existentes = {f["nombre"] for f in emp.inventario}
    faltan = [n for n in equipos_necesarios(sala) if n not in existentes]
    if faltan:
        sys.exit(f"Faltan equipos en la topología: {', '.join(faltan)}")


def calentar(net, pares):
    """Un ping previo para que ARP y las reglas del controlador ya estén listas."""
    for a, b in pares:
        net.get(a).cmd(f"ping -c2 -W2 {net.get(b).IP()}")


def fase(net, sala, nombre, con_carga, duracion):
    s = f"sa{sala}"
    tel, pbx = net.get(f"{s}tel"), net.get("ofpbx")
    caja, vc = net.get(f"{s}caja"), net.get("inetvc")  # PC de caja en videollamada
    upd, srv, bak = net.get("inetupd"), net.get(f"{s}srv"), net.get("ofbak")
    clientes = [net.get(f"{s}cli{i}") for i in (1, 2, 3)]
    limite = duracion + 40

    info(f"\n*** Fase '{nombre}' en Sala {sala} ({duracion} s)\n")
    # Receptores: cada uno calcula sus métricas y las guarda en un archivo local.
    rx_voz, log_voz = m.receptor_udp(pbx, PUERTO_VOZ, limite)
    rx_vid, log_vid = m.receptor_udp(caja, PUERTO_VIDEO, limite)
    receptores_carga = []   # (etiqueta, proceso, ruta)
    if con_carga:
        for i, c in enumerate(clientes):
            p, ruta = m.receptor_tcp(c, PUERTO_BAJADA + i, limite)
            receptores_carga.append(("descargas clientes (bajada)", p, ruta))
        p, ruta = m.receptor_tcp(bak, PUERTO_SUBIDA, limite)
        receptores_carga.append(("respaldo a oficina (subida)", p, ruta))
    time.sleep(1)

    emisores = []
    if con_carga:
        t = duracion + 6
        for i, c in enumerate(clientes):
            emisores.append(m.emisor_tcp(upd, c.IP(), PUERTO_BAJADA + i, t))
        emisores.append(m.emisor_tcp(srv, bak.IP(), PUERTO_SUBIDA, t))
        time.sleep(4)  # que las descargas llenen el enlace antes de medir

    emisores.append(m.emisor_udp(tel, pbx.IP(), PUERTO_VOZ, m.VOIP, duracion))
    emisores.append(m.emisor_udp(vc, caja.IP(), PUERTO_VIDEO, m.VIDEO, duracion))
    p_ping_voz = m.sonda_ping(tel, pbx.IP(), duracion)
    p_ping_vid = m.sonda_ping(caja, vc.IP(), duracion)

    rtt_voz = m.resultado_ping(m.leer(p_ping_voz))
    rtt_vid = m.resultado_ping(m.leer(p_ping_vid))
    for p in emisores:
        m.esperar(p, limite=duracion + 20)
    for p in [rx_voz, rx_vid] + [r[1] for r in receptores_carga]:
        m.esperar(p, limite=15)

    filas = []
    for clase, origen, destino, r, rtt in (
            ("voip", tel.name, pbx.name, m.resultado_udp(log_voz), rtt_voz),
            ("videoconferencia", vc.name, caja.name, m.resultado_udp(log_vid), rtt_vid)):
        if "error" in r:
            info(f"    ERROR en sonda {clase}: {r['error']}\n")
            continue
        fila = {"fase": nombre, "sede": f"Sala {sala}", "clase": clase,
                "origen": origen, "destino": destino, "rtt_ms": rtt["rtt_ms"],
                "latencia_ms": r["latencia_ms"], "latencia_p95_ms": r["latencia_p95_ms"],
                "jitter_ms": r["jitter_ms"], "jitter_max_ms": r["jitter_max_ms"],
                "perdida_pct": r["perdida_pct"], "mbps": r["mbps"]}
        # MOS con la latencia p95: conservador, refleja los paquetes que llegan tarde.
        fila["mos"] = m.mos(r["latencia_p95_ms"], r["jitter_ms"], r["perdida_pct"]) if clase == "voip" else None
        fila["cumple"] = m.evaluar(fila)
        filas.append(fila)

    # Descargas: una fila de bajada (suma de clientes) y otra de subida.
    totales = {}
    for etiqueta, p, ruta in receptores_carga:
        r = m.resultado_tcp(ruta)
        if "error" in r:
            info(f"    ERROR en carga '{etiqueta}': {r['error']}\n")
        totales[etiqueta] = totales.get(etiqueta, 0) + r.get("mbps", 0)
    for etiqueta, mbps in totales.items():
        filas.append({"fase": nombre, "sede": f"Sala {sala}", "clase": etiqueta,
                      "origen": "-", "destino": "-", "mbps": round(mbps, 2), "cumple": "-"})
    return filas


def imprimir(filas):
    info(f"\n    {'Fase':14s} {'Clase':28s} {'RTT':>6s} {'Lat':>6s} {'Lat95':>6s} "
         f"{'Jitter':>6s} {'JitMax':>6s} {'Pérd%':>6s} {'MOS':>5s} {'Mbps':>6s}  Cumple\n")
    fmt = lambda v, d=1: "-" if v is None else f"{v:.{d}f}"  # noqa: E731
    for f in filas:
        info(f"    {f['fase']:14s} {f['clase']:28s} {fmt(f.get('rtt_ms')):>6s} "
             f"{fmt(f.get('latencia_ms')):>6s} {fmt(f.get('latencia_p95_ms')):>6s} "
             f"{fmt(f.get('jitter_ms'), 2):>6s} {fmt(f.get('jitter_max_ms'), 2):>6s} "
             f"{fmt(f.get('perdida_pct'), 2):>6s} {fmt(f.get('mos'), 2):>5s} "
             f"{fmt(f.get('mbps'), 2):>6s}  {f.get('cumple', '-')}\n")
    info("    RTT = ida y vuelta (ping) · Lat / Lat95 = latencia de un sentido, promedio y percentil 95\n")
    info("    La latencia se evalúa y el MOS se calcula con Lat95.\n")


def main():
    p = argparse.ArgumentParser(description="Prueba de congestión sin QoS")
    p.add_argument("--sala", type=int, default=1, choices=[1, 2, 3, 4])
    p.add_argument("--duracion", type=int, default=20, help="segundos de medición por fase")
    p.add_argument("--sin-controlador", action="store_true")
    args = p.parse_args()
    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo")
    if not args.sin_controlador and not controlador_activo():
        sys.exit(AVISO_RYU.format(ip="127.0.0.1", puerto=6633))

    setLogLevel("info")
    with open(CONFIG_DEFECTO) as f:
        cfg = yaml.safe_load(f)
    emp = EmpresaXYZ(cfg, controlador=not args.sin_controlador)
    emp.construir()
    validar(emp, args.sala)
    emp.net.start()
    try:
        emp.configurar()
        info("*** Esperando 5 s a que la red se estabilice\n")
        time.sleep(5)
        s = f"sa{args.sala}"
        calentar(emp.net, [(f"{s}tel", "ofpbx"), (f"{s}caja", "inetvc"),
                           (f"{s}srv", "ofbak")] + [(f"{s}cli{i}", "inetupd") for i in (1, 2, 3)])
        filas = []
        filas += fase(emp.net, args.sala, "sin_carga", False, args.duracion)
        filas += fase(emp.net, args.sala, "con_descargas", True, args.duracion)
        for f in filas:
            f.update({"escenario": f"congestion_sala{args.sala}", "estrategia": "sin_qos"})
        imprimir(filas)
        info(f"\n*** Objetivos: jitter < {m.OBJETIVOS['jitter_ms']} ms, pérdida < "
             f"{m.OBJETIVOS['perdida_pct']} %, latencia p95 < {m.OBJETIVOS['latencia_ms']} ms, "
             f"MOS >= {m.OBJETIVOS['mos']}\n")
        info(f"*** Resultados agregados a {m.guardar(filas)}\n")
    finally:
        emp.limpiar()
        emp.net.stop()


if __name__ == "__main__":
    main()
