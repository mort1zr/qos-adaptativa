#!/usr/bin/env python3
"""
Consultas sobre la telemetría guardada (historia PCIII-16).

Ejemplos (no hace falta sudo; funciona con la red levantada o después):
  python3 controlador/consultas.py demanda --area Contabilidad --minutos 10
  python3 controlador/consultas.py demanda --sede 1 --minutos 5
  python3 controlador/consultas.py demanda --por clase --minutos 10
  python3 controlador/consultas.py enlaces --minutos 10
  python3 controlador/consultas.py flujos --minutos 2 --top 10
  python3 controlador/consultas.py decisiones --minutos 10      # PCIII-19: clase, cola y tiempo
"""
import argparse
import os
import sqlite3
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from controlador.telemetria import DB_DEFECTO, demanda, resumen_decisiones, uso_enlaces  # noqa: E402


def mostrar_demanda(filas, titulo):
    filas = [f for f in filas if f["maximo_mbps"] >= 0.001]   # sin restos de pings (< 1 kbps)
    if not filas:
        print(f"{titulo}: sin tráfico registrado en ese periodo.")
        return
    print(titulo)
    print(f"  {'Sede':20s} {'Área':16s} {'Clase':12s} {'Sentido':8s} {'Promedio':>10s} {'Máximo':>10s}")
    totales = {}
    for f in filas:
        print(f"  {f['sede'] or '-':20s} {f['area']:16s} {f['clase']:12s} {f['sentido']:8s} "
              f"{f['promedio_mbps']:7.3f} Mb {f['maximo_mbps']:7.3f} Mb")
        totales[f["sentido"]] = totales.get(f["sentido"], 0) + f["promedio_mbps"]
    print("  Total promedio: " + ", ".join(f"{s} {v:.3f} Mbps" for s, v in sorted(totales.items())))
    print(f"  (promedio sobre {filas[0]['segundos_con_datos']:.0f} s con telemetría; "
          f"los ratos sin tráfico cuentan como 0; se omite lo menor a 1 kbps)")


def mostrar_enlaces(filas):
    if not filas:
        print("Sin datos de enlaces en ese periodo.")
        return
    print(f"  {'Sede':>4s} {'Sentido':8s} {'Promedio':>10s} {'Máximo':>10s} {'Capacidad':>10s} {'Uso':>7s} {'Descartes':>10s}")
    for f in filas:
        uso = f"{f['uso_pct']:5.1f} %" if f["uso_pct"] is not None else "-"
        print(f"  {f['sede_id']:>4} {f['sentido']:8s} {f['promedio_mbps']:7.2f} Mb {f['maximo_mbps']:7.2f} Mb "
              f"{f['capacidad_mbps'] or 0:7.0f} Mb {uso:>7s} {f['descartes'] or 0:>10}")


def mostrar_flujos(db, minutos, top):
    con = sqlite3.connect(db)
    filas = con.execute(
        "SELECT origen, destino, proto, area, servicio, clase, sentido, "
        "SUM(mbps*segundos)/? AS prom, MAX(mbps) FROM flujos WHERE ts >= ? "
        "GROUP BY origen, destino, proto, sentido ORDER BY prom DESC LIMIT ?",
        (minutos * 60, time.time() - minutos * 60, top)).fetchall()
    con.close()
    if not filas:
        print("Sin flujos en ese periodo.")
        return
    print(f"  {'Origen':12s} {'Destino':12s} {'Proto':>5s} {'Área':14s} {'Servicio':16s} {'Clase':12s} "
          f"{'Sentido':7s} {'Prom.':>8s} {'Máx.':>8s}")
    for o, d, p, a, s, c, se, prom, mx in filas:
        print(f"  {o:12s} {d:12s} {p:>5} {a:14s} {s:16s} {c:12s} {se:7s} {prom:6.2f} Mb {mx:6.2f} Mb")


def mostrar_decisiones(filas, minutos):
    if not filas:
        print(f"Sin decisiones del controlador en los últimos {minutos:g} minutos.")
        return
    print(f"Decisiones del controlador (una por flujo nuevo) en los últimos {minutos:g} minutos:")
    print(f"  {'Clasificador':12s} {'Clase':12s} {'Cola':>4s} {'Flujos':>7s} {'Por adel.':>9s} "
          f"{'p50':>8s} {'p95':>8s} {'Máx.':>8s}")
    for f in filas:
        print(f"  {f['clasificador']:12s} {f['clase']:12s} {f['cola']:>4} {f['decisiones']:>7} {f['proactivas']:>9} "
              f"{f['p50_ms']:5.2f} ms {f['p95_ms']:5.2f} ms {f['max_ms']:5.2f} ms")
    print("  (tiempo desde que llega el primer paquete hasta que la regla con su cola sale al switch;\n"
          "   'por adelantado': flujos que ya iban a su cola por una regla instalada antes, sin esperar)")


def main():
    p = argparse.ArgumentParser(description="Consultas sobre la telemetría")
    p.add_argument("--db", default=DB_DEFECTO)
    sub = p.add_subparsers(dest="accion", required=True)
    d = sub.add_parser("demanda", help="demanda por área y clase")
    d.add_argument("--area")
    d.add_argument("--sede", type=int)
    d.add_argument("--minutos", type=float, default=10)
    d.add_argument("--por", choices=("area", "clase"), default="area")
    e = sub.add_parser("enlaces", help="uso de los enlaces de acceso")
    e.add_argument("--minutos", type=float, default=10)
    f = sub.add_parser("flujos", help="flujos con más tráfico")
    f.add_argument("--minutos", type=float, default=5)
    f.add_argument("--top", type=int, default=10)
    c = sub.add_parser("decisiones", help="clase y cola elegidas por el controlador, y su tiempo")
    c.add_argument("--minutos", type=float, default=10)
    c.add_argument("--sede", type=int)
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"No existe {args.db}: arranca Ryu con 'ryu-manager controlador/qos_app.py' "
                 f"y levanta la red para que empiece a guardar telemetría.")
    if args.accion == "demanda":
        quien = args.area or (f"Sede {args.sede}" if args.sede is not None else "toda la red")
        filas = demanda(args.db, args.minutos, area=args.area, sede_id=args.sede, por=args.por)
        mostrar_demanda(filas, f"Demanda de {quien} en los últimos {args.minutos:g} minutos:")
    elif args.accion == "enlaces":
        print(f"Uso de los enlaces de acceso en los últimos {args.minutos:g} minutos:")
        mostrar_enlaces(uso_enlaces(args.db, args.minutos))
    elif args.accion == "decisiones":
        mostrar_decisiones(resumen_decisiones(args.db, args.minutos, sede_id=args.sede), args.minutos)
    else:
        print(f"Flujos con más tráfico en los últimos {args.minutos:g} minutos:")
        mostrar_flujos(args.db, args.minutos, args.top)


if __name__ == "__main__":
    main()
