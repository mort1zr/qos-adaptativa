#!/usr/bin/env python3
"""
Genera tráfico por perfil de aplicación y verifica cómo lo ve el controlador
(historia PCIII-17).

  python3 trafico/generar.py --listar                        # perfiles disponibles
  python3 trafico/generar.py --plan --perfil todos --sede 1  # qué haría (sin red)
  sudo python3 trafico/generar.py --perfil camara_remota --sede 2 --duracion 60
  sudo python3 trafico/generar.py --perfil todos --sede 1 --duracion 60
  sudo python3 trafico/generar.py --perfil todos --sede 1 --con-cargas

'todos' es un día normal: todos los perfiles menos las cargas masivas (descargas
y respaldo), que agregan los escenarios o --con-cargas. Con todas las sedes a la
vez la CPU de la VM puede no alcanzar y las tasas bajan (limitación declarada).

Con Ryu corriendo controlador/qos_app.py, al terminar compara cada perfil con
la telemetría: clase asignada (debe ser la esperada) y tasa medida.
Resultados: experimentos/resultados/perfiles_trafico.csv
"""
import argparse
import csv
import datetime
import os
import sqlite3
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "topologia"))

from trafico.generador import Generador, cargar_perfiles  # noqa: E402

CSV = os.path.join(RAIZ, "experimentos", "resultados", "perfiles_trafico.csv")


CABECERA_TCP = 66          # bytes por paquete (Ethernet + IP + TCP con opciones)
MSS = 1448


def esperado_mbps(a):
    """Tasa aproximada que debería ver el switch (None si es TCP elástico).
    En TCP suma las cabeceras: cada transacción lleva sus paquetes de datos más
    unos 4 paquetes de control (ACK, PUSH); en mensajes chicos pesan mucho."""
    if a["transporte"] == "udp":
        return a["mbps"] + a.get("mbps_vuelta", 0)
    if a["patron"] != "transacciones":
        return None
    datos = a["peticion"] + a["respuesta"]
    paquetes = -(-a["peticion"] // MSS) - (-a["respuesta"] // MSS) + 4
    if a.get("nueva_conexion"):
        paquetes += 6                      # abrir y cerrar la conexión
    por_tx = (datos + paquetes * CABECERA_TCP) * 8 / 1e6
    return por_tx * (a["tasa"] if "tasa" in a else 1 / a["periodo"])


def agrupar(acciones):
    """Une las acciones que comparten flujo (mismo perfil, sede, origen y destino):
    el switch las ve como un solo flujo (p. ej. dos cámaras desde el mismo NVR)."""
    grupos = {}
    for a in acciones:
        clave = (a["perfil"], a["sede"], a["origen"], a["destino"], a["transporte"])
        if clave not in grupos:
            grupos[clave] = dict(a, n=1, esperado=esperado_mbps(a))
        else:
            g = grupos[clave]
            g["n"] += 1
            e = esperado_mbps(a)
            g["esperado"] = None if g["esperado"] is None or e is None else g["esperado"] + e
    return list(grupos.values())


def medir(db, a, desde, hasta):
    """Mbps promedio y clases que la telemetría registró entre origen y destino en su sede."""
    con = sqlite3.connect(db)
    filas = con.execute(
        "SELECT clase, SUM(bytes) FROM flujos WHERE sede_id = ? AND ts > ? AND ts <= ? AND "
        "((origen = ? AND destino = ?) OR (origen = ? AND destino = ?)) GROUP BY clase",
        (a["sede"], desde, hasta, a["origen"], a["destino"], a["destino"], a["origen"])).fetchall()
    con.close()
    total = sum(b for _, b in filas)
    return total * 8 / (hasta - desde) / 1e6, sorted(c for c, _ in filas)


def inventario_csv():
    from controlador.inventario import Inventario
    inv = Inventario()
    if not inv.por_ip:
        sys.exit("No hay topologia/inventario.csv: levanta la topología una vez para generarlo.")
    return list(inv.por_ip.values())


def main():
    p = argparse.ArgumentParser(description="Tráfico por perfil de aplicación")
    p.add_argument("--perfil", default="todos", help="nombre del perfil o 'todos'")
    p.add_argument("--sede", default="1", help="0 = oficina, 1-4 = salas, o 'todas'")
    p.add_argument("--duracion", type=int, default=60)
    p.add_argument("--intensidad", type=float, default=1.0)
    p.add_argument("--semilla", type=int, default=7)
    p.add_argument("--listar", action="store_true")
    p.add_argument("--plan", action="store_true", help="muestra el plan sin levantar la red")
    p.add_argument("--con-cargas", action="store_true",
                   help="con 'todos', agrega descargas y respaldo (saturan el enlace)")
    p.add_argument("--datapath", choices=("kernel", "user"), default="kernel")
    args = p.parse_args()

    datos = cargar_perfiles()
    if args.listar:
        for nombre, pf in datos["perfiles"].items():
            print(f"  {nombre:16s} {pf['sedes']:8s} {pf['clase_esperada']:12s} {pf['descripcion']}")
        return

    cargas = ("descargas", "respaldo")
    if args.perfil == "todos":
        perfiles = [p for p in datos["perfiles"] if args.con_cargas or p not in cargas]
    else:
        perfiles = [args.perfil]
    if args.plan:
        gen = Generador(None, inventario_csv(), semilla=args.semilla, perfiles=datos)
        sedes = sorted({f["sede_id"] for f in gen.inv if isinstance(f["sede_id"], int)})
        for sede in (sedes if args.sede == "todas" else [int(args.sede)]):
            for perfil in perfiles:
                for a in gen.plan(perfil, sede, args.intensidad, args.duracion):
                    e = esperado_mbps(a)
                    print(f"  sede {sede}  {perfil:16s} {a['origen']:9s} -> {a['destino']:9s} "
                          f"{a['transporte']}/{a['puerto']:<5} {'~%.2f Mbps' % e if e else 'elástico':>12s} "
                          f"{a['clase_esperada']}")
        return

    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo (levanta la red de Mininet)")
    import yaml
    from mininet.log import info, setLogLevel
    from empresa_xyz import AVISO_RYU, CONFIG_DEFECTO, EmpresaXYZ, controlador_activo
    from controlador.telemetria import leer_config
    if not controlador_activo():
        sys.exit(AVISO_RYU.format(ip="127.0.0.1", puerto=6633))
    setLogLevel("info")
    with open(CONFIG_DEFECTO) as f:
        cfg = yaml.safe_load(f)
    tel = leer_config()
    emp = EmpresaXYZ(cfg, datapath=args.datapath)
    emp.construir()
    emp.net.start()
    filas, acciones = [], []
    try:
        emp.configurar(estrategia="colas")
        info("*** Esperando 8 s a que los switches se conecten a Ryu\n")
        time.sleep(8)
        gen = Generador(emp.net, emp.inventario, semilla=args.semilla, perfiles=datos)
        gen.levantar_servidores(duracion=args.duracion + 120)
        time.sleep(2)
        sedes = sorted({f["sede_id"] for f in emp.inventario if isinstance(f["sede_id"], int)})
        inicio = time.time()
        for sede in (sedes if args.sede == "todas" else [int(args.sede)]):
            for perfil in perfiles:
                acciones += gen.iniciar(perfil, sede, args.duracion, args.intensidad)
        info(f"*** {len(acciones)} flujos de {len(perfiles)} perfil(es) durante {args.duracion} s\n")
        for a in acciones:
            info(f"    {a['perfil']:16s} {a['origen']:9s} -> {a['destino']:9s} {a['transporte']}/{a['puerto']}\n")
        time.sleep(args.duracion)
        gen.esperar(limite=20)
        fin = time.time()
        time.sleep(tel["intervalo_s"] * 2)
        gen.detener()

        db = tel["base_datos"]
        if os.path.exists(db):
            for a in agrupar(acciones):
                # Todo el periodo del tráfico (incluido el último sondeo).
                medido, clases = medir(db, a, inicio, fin + tel["intervalo_s"])
                medido = medido * (fin + tel["intervalo_s"] - inicio) / (fin - inicio)
                if not clases:
                    cumple = "sin tráfico"         # p. ej. un POS que no cobró en ese minuto
                elif clases == [a["clase_esperada"]]:
                    cumple = "sí"
                else:
                    cumple = "no"
                e = a["esperado"]
                filas.append({"fecha": datetime.datetime.now().isoformat(timespec="seconds"),
                              "semilla": args.semilla, "perfil": a["perfil"], "sede": a["sede"],
                              "origen": a["origen"], "destino": a["destino"], "flujos": a["n"],
                              "transporte": a["transporte"],
                              "esperado_mbps": round(e, 3) if e else "", "medido_mbps": round(medido, 3),
                              "clase_esperada": a["clase_esperada"], "clases_medidas": "+".join(clases),
                              "cumple": cumple})
    finally:
        emp.limpiar()
        emp.net.stop()

    if not filas:
        print("\nNo hay telemetría para verificar (¿Ryu corre controlador/qos_app.py?).")
        return
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    nuevo = not os.path.exists(CSV)
    with open(CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        if nuevo:
            w.writeheader()
        w.writerows(filas)
    print(f"\n    {'Perfil':16s} {'Sede':>4s} {'Origen -> destino':22s} {'Transp.':7s} "
          f"{'Esperado':>9s} {'Medido':>9s}  {'Clase':12s} Cumple")
    for f in filas:
        esp = f"{f['esperado_mbps']:.3f}" if f["esperado_mbps"] != "" else "elástico"
        n = f" x{f['flujos']}" if f["flujos"] > 1 else ""
        print(f"    {f['perfil']:16s} {f['sede']:>4} {f['origen'] + ' -> ' + f['destino']:22s} "
              f"{f['transporte'] + n:7s} {esp:>9s} {f['medido_mbps']:9.3f}  {f['clases_medidas'] or '-':12s} {f['cumple']}")
    con_trafico = [f for f in filas if f["cumple"] != "sin tráfico"]
    ok = sum(1 for f in con_trafico if f["cumple"] == "sí")
    print(f"\n*** {ok}/{len(con_trafico)} flujos con tráfico recibieron la clase esperada "
          f"({len(filas) - len(con_trafico)} sin tráfico en el periodo). Resultados en {CSV}")
    print("    Esperado: tasa de la aplicación más las cabeceras; elástico = TCP que usa lo que haya.")


if __name__ == "__main__":
    main()
