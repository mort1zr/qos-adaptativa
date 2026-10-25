#!/usr/bin/env python3
"""
Escenarios reproducibles de la empresa (historia PCIII-18).

  python3 escenarios/escenario.py --listar
  python3 escenarios/escenario.py --plan --nombre sorteo --ruido 0.1
  sudo python3 escenarios/escenario.py --nombre sorteo --estrategia fila_corta --sala 1
  sudo python3 escenarios/escenario.py --todos --estrategia sin_qos,fila_corta --sala 4

Levanta la red una sola vez y, para cada estrategia y cada escenario, recorre
sus fases: genera el tráfico de los perfiles (trafico/), mide la voz y los
pagos con sondas y lee el uso del enlace de la sala. El reloj simulado se
publica en datos/reloj.json y cada fase queda registrada en datos/contexto.csv
(para unir la telemetría con el escenario, la hora y la estrategia).

Estrategias: sin_qos (una cola, FIFO larga: red sin gestionar) y fila_corta
(6 colas, todo en "masivo", fila corta: la estrategia de control). 'estatica'
llega en el Sprint 3 (PCIII-21) e 'ia' en los Sprints 4-5.

Con la misma --semilla el tráfico es el mismo; --ruido 0.1 varía cada
intensidad ±10 % (reproducible con la semilla) para no validar a la IA con
exactamente los mismos datos con los que aprende.
Resultados: experimentos/resultados/escenarios.csv
"""
import argparse
import csv
import datetime
import json
import os
import random
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
# La raíz va primero: experimentos/trafico.py no debe tapar a la carpeta trafico/.
sys.path.insert(0, RAIZ)
for ruta in (os.path.join(RAIZ, "topologia"), os.path.join(RAIZ, "experimentos")):
    if ruta not in sys.path:
        sys.path.append(ruta)

import yaml  # noqa: E402

from escenarios.reloj import DIAS, RelojSimulado, normalizar_dia  # noqa: E402
from trafico.generador import APLICACIONES, Generador, cargar_perfiles  # noqa: E402

ESCENARIOS = os.path.join(AQUI, "escenarios.yaml")
CSV = os.path.join(RAIZ, "experimentos", "resultados", "escenarios.csv")
CONTEXTO = os.path.join(RAIZ, "datos", "contexto.csv")
ESTRATEGIAS = {"sin_qos": "sin_qos", "fila_corta": "colas"}     # nombre -> estrategia de la topología
FUTURAS = {"estatica": "el Sprint 3 (PCIII-21)", "ia": "los Sprints 4 y 5"}
PUERTO_VOZ = 5001


class EscenarioInvalido(ValueError):
    pass


def cargar_escenarios(ruta: str = ESCENARIOS, perfiles: dict = None) -> dict:
    with open(ruta) as f:
        datos = yaml.safe_load(f)
    nombres_perfiles = set((perfiles or cargar_perfiles())["perfiles"])
    errores = []
    if not datos.get("reloj", {}).get("factor", 0) > 0:
        errores.append("reloj.factor debe ser mayor que 0")
    for nombre, e in datos.get("escenarios", {}).items():
        inicio = e.get("inicio", {})
        if normalizar_dia(str(inicio.get("dia", ""))) not in DIAS:
            errores.append(f"{nombre}: día de inicio desconocido '{inicio.get('dia')}'")
        try:
            hh, mm = (int(x) for x in str(inicio.get("hora", "")).split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
        except (ValueError, AssertionError):
            errores.append(f"{nombre}: hora de inicio inválida '{inicio.get('hora')}' (usa HH:MM)")
        if not e.get("fases"):
            errores.append(f"{nombre}: necesita al menos una fase")
        for i, fase in enumerate(e.get("fases") or [], 1):
            etiqueta = f"{nombre}/{fase.get('nombre', i)}"
            if not (isinstance(fase.get("duracion_s"), (int, float)) and fase["duracion_s"] >= 10):
                errores.append(f"{etiqueta}: duracion_s debe ser de al menos 10 s")
            for lugar in ("sala", "oficina"):
                for perfil, valor in (fase.get(lugar) or {}).items():
                    if perfil not in nombres_perfiles:
                        errores.append(f"{etiqueta}: perfil desconocido '{perfil}'")
                    elif not isinstance(valor, (int, float)) or valor < 0:
                        errores.append(f"{etiqueta}: la intensidad de '{perfil}' debe ser un número >= 0")
    if errores:
        raise EscenarioInvalido("Escenarios inválidos:\n  - " + "\n  - ".join(errores))
    return datos


def plan_escenario(datos: dict, nombre: str, semilla: int = 7, ruido: float = 0.0,
                   escala: float = 1.0) -> list:
    """Fases con sus intensidades finales (con ruido reproducible). No toca la red."""
    if nombre not in datos["escenarios"]:
        raise EscenarioInvalido(f"escenario desconocido: {nombre} (hay: {', '.join(datos['escenarios'])})")
    rng = random.Random(f"{semilla}-{nombre}")
    fases = []
    for fase in datos["escenarios"][nombre]["fases"]:
        f = {"nombre": fase["nombre"], "duracion_s": max(10, round(fase["duracion_s"] * escala))}
        for lugar in ("sala", "oficina"):
            f[lugar] = {p: round(max(0.0, v * (1 + rng.uniform(-ruido, ruido))), 3) if ruido else v
                        for p, v in sorted((fase.get(lugar) or {}).items())}
        fases.append(f)
    return fases


# ---------------- ejecución en la red ----------------
def poner_estrategia(emp, estrategia):
    emp.colas.hoja = "fifo" if estrategia == "sin_qos" else "pfifo:64"
    for _, puerto, mbps, _ in emp.puertos_acceso:
        if ESTRATEGIAS[estrategia] == "colas":
            emp.colas.aplicar(puerto, mbps)
        else:
            emp.colas.linea_base(puerto, mbps)


def correr_fase(emp, gen, sala, fase, sondas, m, reloj, nombre, estrategia):
    net, s, dur = emp.net, f"sa{sala}", fase["duracion_s"]
    cuellos = {sentido: p for sw, p, _, sentido in emp.puertos_acceso if sw == f"acc{sala}"}
    capacidad = next(mb for sw, _, mb, _ in emp.puertos_acceso if sw == f"acc{sala}")
    t0 = time.time()
    reloj.guardar(nombre, fase["nombre"], estrategia=estrategia, sala=sala)
    hora = reloj.describir(t0)
    for perfil, i in fase["sala"].items():
        gen.iniciar(perfil, sala, dur, i)
    for perfil, i in fase["oficina"].items():
        gen.iniciar(perfil, 0, dur, i)

    # Sondas: arrancan 2 s después y terminan 2 s antes, para medir la fase "llena".
    sonda_dur = max(5, dur - 4)
    tel, pbx = net.get(f"{s}tel"), net.get("ofpbx")
    # La llamada va en los dos sentidos: subida (teléfono de la sala -> central) y
    # bajada (central -> teléfono). Se evalúa por el peor de los dos, como se oiría.
    rx_voz = {}
    if sondas.get("voz"):
        rx_voz = {"subida": m.receptor_udp(pbx, PUERTO_VOZ, dur + 30),
                  "bajada": m.receptor_udp(tel, PUERTO_VOZ, dur + 30)}
    ruta_pagos = f"/tmp/qos_mediciones/pagos_{s}.json"
    os.makedirs(os.path.dirname(ruta_pagos), exist_ok=True)
    if os.path.exists(ruta_pagos):
        os.remove(ruta_pagos)
    time.sleep(2)
    b0 = {k: emp.colas.bytes_enviados(p) for k, p in cuellos.items()}
    tb0 = time.time()
    procesos = []
    if rx_voz:
        procesos.append(m.emisor_udp(tel, pbx.IP(), PUERTO_VOZ, m.VOIP, sonda_dur))
        procesos.append(m.emisor_udp(pbx, tel.IP(), PUERTO_VOZ, m.VOIP, sonda_dur))
    pg = sondas.get("pagos")
    if pg:
        destino = net.get("inetpago1").IP()
        procesos.append(net.get(f"{s}pos1").popen(
            [gen.python, APLICACIONES, "cliente", "--destino", destino, "--puerto", "443",
             "--patron", "transacciones", "--periodo", str(pg["periodo_s"]), "--nueva-conexion",
             "--peticion", str(pg["peticion"]), "--respuesta", str(pg["respuesta"]),
             "--variacion", "0", "--duracion", str(sonda_dur), "--salida", ruta_pagos],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    restante = dur - (time.time() - t0)
    time.sleep(max(0, restante - 2))
    b1 = {k: emp.colas.bytes_enviados(p) for k, p in cuellos.items()}
    tb1 = time.time()
    for p in procesos:
        m.esperar(p, limite=20)
    for rx, _ in rx_voz.values():
        m.esperar(rx, limite=15)
    gen.esperar(limite=15)
    gen.procesos = [x for x in gen.procesos if "servidor" in x[0]]
    t1 = time.time()

    uso = {k: 100 * (b1[k] - b0[k]) * 8 / (tb1 - tb0) / 1e6 / capacidad for k in cuellos}
    fila = {"fase": fase["nombre"], "hora_simulada": hora, "duracion_s": dur,
            "uso_bajada_pct": round(uso["bajada"], 1), "uso_subida_pct": round(uso["subida"], 1)}
    if rx_voz:
        sentidos = {}
        for sentido, (_, ruta) in rx_voz.items():
            r = m.resultado_udp(ruta)
            if "error" in r:
                r = {"latencia_p95_ms": None, "jitter_ms": None, "perdida_pct": 100.0, "mos": 1.0}
            else:
                r["mos"] = m.mos(r["latencia_p95_ms"], r["jitter_ms"], r["perdida_pct"])
            sentidos[sentido] = r
            fila.update({f"voz_{sentido}_lat95_ms": r["latencia_p95_ms"],
                         f"voz_{sentido}_jitter_ms": r["jitter_ms"],
                         f"voz_{sentido}_perdida_pct": r["perdida_pct"], f"voz_{sentido}_mos": r["mos"]})
        peor = min(sentidos.values(), key=lambda r: r["mos"])
        fila.update(voz_lat95_ms=max((r["latencia_p95_ms"] or 0) for r in sentidos.values()) or None,
                    voz_jitter_ms=max((r["jitter_ms"] or 0) for r in sentidos.values()),
                    voz_perdida_pct=max(r["perdida_pct"] for r in sentidos.values()),
                    voz_mos=peor["mos"])
        if peor["latencia_p95_ms"] is None:
            fila["cumple_voz"] = "no (sin llamada)"
        else:
            fila["cumple_voz"] = m.evaluar({"latencia_p95_ms": fila["voz_lat95_ms"],
                                            "jitter_ms": fila["voz_jitter_ms"],
                                            "perdida_pct": fila["voz_perdida_pct"], "mos": fila["voz_mos"]})
    if pg:
        try:
            with open(ruta_pagos) as f:
                rp = json.load(f)
        except (OSError, ValueError):
            rp = {"transacciones": 0, "errores": 1}
        fila.update(pagos_n=rp.get("transacciones", 0), pagos_errores=rp.get("errores", 0),
                    pagos_p95_ms=rp.get("p95_ms"))
    return fila, t0, t1


def guardar_csv(ruta, filas):
    if not filas:
        return
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nuevo = not os.path.exists(ruta)
    campos = list(filas[0].keys())
    for f in filas[1:]:
        campos += [k for k in f if k not in campos]
    with open(ruta, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def imprimir(filas):
    fmt = lambda v, d=1: "-" if v in (None, "") else f"{v:.{d}f}"  # noqa: E731
    actual = None
    for f in filas:
        if (f["escenario"], f["estrategia"]) != actual:
            actual = (f["escenario"], f["estrategia"])
            print(f"\n  {f['escenario']} · {f['estrategia']} · Sala {f['sala']}")
            print(f"    {'Fase':16s} {'Hora sim.':14s} {'Uso baj/sub':>12s} {'Voz p95 sub/baj':>16s} "
                  f"{'Jitter':>7s} {'Pérd%':>6s} {'MOS':>5s} {'Pagos p95':>10s}  Cumple voz / pagos")
        voz = f"{fmt(f.get('voz_subida_lat95_ms'), 0)}/{fmt(f.get('voz_bajada_lat95_ms'), 0)} ms"
        print(f"    {f['fase']:16s} {f['hora_simulada']:14s} "
              f"{fmt(f['uso_bajada_pct'], 0):>5s}/{fmt(f['uso_subida_pct'], 0):<4s} % "
              f"{voz:>16s} {fmt(f.get('voz_jitter_ms'), 2):>7s} "
              f"{fmt(f.get('voz_perdida_pct'), 2):>6s} {fmt(f.get('voz_mos'), 2):>5s} "
              f"{fmt(f.get('pagos_p95_ms'), 0):>7s} ms  {f.get('cumple_voz', '-')} / {f.get('cumple_pagos', '-')}")
    print("\n    Voz: se mide la llamada en los dos sentidos; jitter, pérdida y MOS son los del peor.")


def main():
    p = argparse.ArgumentParser(description="Escenarios reproducibles de la empresa")
    p.add_argument("--nombre", help="escenario a correr")
    p.add_argument("--todos", action="store_true", help="los 5 escenarios, uno tras otro")
    p.add_argument("--estrategia", default="fila_corta",
                   help="sin_qos, fila_corta (o varias separadas por coma)")
    p.add_argument("--sala", type=int, default=1, choices=[1, 2, 3, 4])
    p.add_argument("--semilla", type=int, default=7)
    p.add_argument("--ruido", type=float, default=0.0, help="variación aleatoria de las intensidades (0.1 = ±10 %%)")
    p.add_argument("--escala", type=float, default=1.0, help="multiplica la duración de las fases (pruebas rápidas)")
    p.add_argument("--listar", action="store_true")
    p.add_argument("--plan", action="store_true", help="muestra las fases e intensidades sin levantar la red")
    p.add_argument("--datapath", choices=("kernel", "user"), default="kernel")
    args = p.parse_args()

    perfiles = cargar_perfiles()
    datos = cargar_escenarios(perfiles=perfiles)
    if args.listar:
        for nombre, e in datos["escenarios"].items():
            dur = sum(f["duracion_s"] for f in e["fases"])
            print(f"  {nombre:22s} {e['inicio']['dia']:9s} {e['inicio']['hora']}  {len(e['fases'])} fase(s), "
                  f"{dur} s\n      {e['descripcion']}")
        return
    nombres = list(datos["escenarios"]) if args.todos else [args.nombre]
    if not nombres or nombres == [None]:
        sys.exit("Indica --nombre <escenario> o --todos (ver --listar)")
    estrategias = [e.strip() for e in args.estrategia.split(",")]
    for e in estrategias:
        if e in FUTURAS:
            sys.exit(f"La estrategia '{e}' se implementa en {FUTURAS[e]}. Hoy: {', '.join(ESTRATEGIAS)}.")
        if e not in ESTRATEGIAS:
            sys.exit(f"Estrategia desconocida: {e}. Hoy: {', '.join(ESTRATEGIAS)}.")
    planes = {n: plan_escenario(datos, n, args.semilla, args.ruido, args.escala) for n in nombres}
    if args.plan:
        for n, fases in planes.items():
            print(f"\n  {n} (semilla {args.semilla}, ruido {args.ruido})")
            for f in fases:
                print(f"    {f['nombre']:16s} {f['duracion_s']:>4} s  sala: {f['sala']}")
                if f["oficina"]:
                    print(f"    {'':16s} {'':>4}    oficina: {f['oficina']}")
        return

    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo (levanta la red de Mininet)")
    from mininet.log import info, setLogLevel
    from empresa_xyz import AVISO_RYU, CONFIG_DEFECTO, EmpresaXYZ, controlador_activo
    import medicion as m
    if not controlador_activo():
        sys.exit(AVISO_RYU.format(ip="127.0.0.1", puerto=6633))
    setLogLevel("info")
    with open(CONFIG_DEFECTO) as f:
        cfg = yaml.safe_load(f)
    emp = EmpresaXYZ(cfg, datapath=args.datapath)
    emp.construir()
    emp.net.start()
    filas, contexto = [], []
    fecha = datetime.datetime.now().isoformat(timespec="seconds")
    objetivo_pagos = datos.get("objetivos", {}).get("pagos_p95_ms", 500)
    try:
        emp.configurar(estrategia=ESTRATEGIAS[estrategias[0]])
        info("*** Esperando 8 s a que los switches se conecten a Ryu\n")
        time.sleep(8)
        gen = Generador(emp.net, emp.inventario, semilla=args.semilla, perfiles=perfiles)
        total = sum(f["duracion_s"] + 6 for fs in planes.values() for f in fs) * len(estrategias)
        gen.levantar_servidores(duracion=total + 300)
        s = f"sa{args.sala}"
        for a, b in ((f"{s}tel", "ofpbx"), (f"{s}pos1", "inetpago1"), (f"{s}cli1", "inetstr")):
            emp.net.get(a).cmd(f"ping -c2 -W2 {emp.net.get(b).IP()}")
        info(f"*** {len(nombres)} escenario(s) x {len(estrategias)} estrategia(s) en la Sala {args.sala}: "
             f"unos {total // 60 + 1} min\n")
        for estrategia in estrategias:
            poner_estrategia(emp, estrategia)
            time.sleep(2)
            for nombre in nombres:
                e = datos["escenarios"][nombre]
                reloj = RelojSimulado(e["inicio"]["dia"], e["inicio"]["hora"], datos["reloj"]["factor"])
                info(f"\n*** {nombre} · {estrategia} · empieza {reloj.describir()} (simulado)\n")
                for fase in planes[nombre]:
                    info(f"    fase {fase['nombre']} ({fase['duracion_s']} s, {reloj.describir()})\n")
                    fila, t0, t1 = correr_fase(emp, gen, args.sala, fase, datos.get("sondas", {}), m,
                                               reloj, nombre, estrategia)
                    if "pagos_p95_ms" in fila:
                        ok = (fila["pagos_n"] > 0 and fila["pagos_errores"] == 0
                              and fila["pagos_p95_ms"] is not None and fila["pagos_p95_ms"] <= objetivo_pagos)
                        fila["cumple_pagos"] = "sí" if ok else "no"
                    filas.append({"fecha": fecha, "escenario": nombre, "estrategia": estrategia,
                                  "sala": args.sala, "semilla": args.semilla, "ruido": args.ruido, **fila})
                    contexto.append({"inicio_real": round(t0, 3), "fin_real": round(t1, 3), "escenario": nombre,
                                     "estrategia": estrategia, "sala": args.sala, "fase": fase["nombre"],
                                     "inicio_simulado": reloj.simulado(t0).isoformat(timespec="minutes"),
                                     "factor": reloj.factor, "semilla": args.semilla, "ruido": args.ruido})
    finally:
        try:
            gen.detener()
        except NameError:
            pass
        emp.limpiar()
        emp.net.stop()
        guardar_csv(CSV, filas)
        guardar_csv(CONTEXTO, contexto)
    imprimir(filas)
    print(f"\n    Objetivos: voz (jitter < {m.OBJETIVOS['jitter_ms']:g} ms, pérdida < {m.OBJETIVOS['perdida_pct']:g} %, "
          f"latencia p95 < {m.OBJETIVOS['latencia_ms']:g} ms, MOS >= {m.OBJETIVOS['mos']:g}); "
          f"pagos p95 <= {objetivo_pagos} ms y sin errores.")
    print(f"*** Resultados agregados a {CSV}\n*** Contexto de cada fase (para la IA) en {CONTEXTO}")


if __name__ == "__main__":
    main()
