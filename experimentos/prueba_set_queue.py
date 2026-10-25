#!/usr/bin/env python3
"""
Cada flujo a su cola en tiempo real (historia PCIII-19).

Con Ryu corriendo controlador/qos_app.py, en la Sala elegida y con 6 colas por
enlace, comprueba:

  1. Una decisión por flujo. Un ping de 30 paquetes entre el teléfono de la sala
     y la central: el controlador solo ve el PRIMER paquete de cada sentido en
     cada switch de acceso (4 decisiones); el resto lo despacha el switch con la
     regla instalada. Se mide cuánto más tarda el primer ping que los demás.
  2. Cada clase cae en su cola. Fase "respaldo" del escenario
     respaldo_en_atencion (hay tráfico de las 6 clases) con la estrategia
     prioridad: los bytes de cada cola (contadores de tc) se comparan con los de
     cada clase según la telemetría. Con fila_corta, todo debe ir a la cola 0.
  3. La prioridad se nota: esa misma fase con fila_corta y con prioridad.
  4. Las reglas vencen: tras idle_timeout_s sin tráfico no quedan reglas por
     flujo en el switch de la sala.
  Además: tiempo de cada decisión del controlador (objetivo: p95 < 50 ms).

Uso (Ryu con controlador/qos_app.py en otra terminal):
  sudo python3 experimentos/prueba_set_queue.py            # Sala 1, ~5 min
Resultados: experimentos/resultados/prueba_set_queue.csv
"""
import argparse
import csv
import datetime
import os
import re
import sqlite3
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)          # primero: experimentos/trafico.py no debe tapar a trafico/
for ruta in (os.path.join(RAIZ, "topologia"), AQUI):
    if ruta not in sys.path:
        sys.path.append(ruta)

import yaml  # noqa: E402

from controlador import api  # noqa: E402
from controlador.telemetria import leer_config, percentil  # noqa: E402
from escenarios.escenario import cargar_escenarios, correr_fase, plan_escenario, poner_estrategia  # noqa: E402
from escenarios.reloj import RelojSimulado  # noqa: E402
from trafico.generador import Generador, cargar_perfiles  # noqa: E402

CSV = os.path.join(AQUI, "resultados", "prueba_set_queue.csv")
CAMPOS = ["fecha", "sala", "prueba", "variante", "clase", "cola", "medida", "valor", "criterio", "cumple"]
OBJETIVO_DECISION_MS = 50
ESCENARIO, FASE = "respaldo_en_atencion", "respaldo"


def fila(prueba, medida, valor, criterio="-", cumple="-", **extra):
    return dict(prueba=prueba, medida=medida, valor=valor, criterio=criterio, cumple=cumple, **extra)


def si(condicion):
    return "sí" if condicion else "no"


# ---------------- 1. una decisión por flujo ----------------
def prueba_decision(emp, sala, db, intervalo):
    from mininet.log import info
    info("\n*** Prueba 1 · una decisión por flujo (ping de 30 paquetes teléfono -> central)\n")
    poner_estrategia(emp, "prioridad")
    time.sleep(1)
    tel, pbx = emp.net.get(f"sa{sala}tel"), emp.net.get("ofpbx")
    antes = api.estado()["contadores"]
    t0 = time.time()
    salida = tel.cmd(f"ping -c 30 -i 0.2 {pbx.IP()}")
    rtt = [float(x) for x in re.findall(r"time=([\d.]+)", salida)]
    time.sleep(intervalo + 2)                       # las decisiones se guardan en el sondeo
    despues = api.estado()["contadores"]
    con = sqlite3.connect(db)
    decisiones = con.execute(
        "SELECT dpid, sentido, clase, cola, ms FROM decisiones WHERE ts >= ? AND proto = 1 AND "
        "((origen_ip = ? AND destino_ip = ?) OR (origen_ip = ? AND destino_ip = ?))",
        (t0 - 1, tel.IP(), pbx.IP(), pbx.IP(), tel.IP())).fetchall()
    con.close()
    clases = sorted({(c, q) for _, _, c, q, _ in decisiones})
    ok = len(decisiones) == 4 and clases == [("tiempo_real", emp.colas.pol.cola("tiempo_real"))]
    primero = rtt[0] if rtt else None
    mediana = percentil(rtt[1:], 50) if len(rtt) > 1 else None
    info(f"    {len(rtt)} respuestas; decisiones del controlador para este flujo: {len(decisiones)} "
         f"(2 switches de acceso x 2 sentidos), clase {clases}\n"
         f"    packet-in en switches de acceso durante la prueba: "
         f"{despues['packet_in_acceso'] - antes['packet_in_acceso']}\n"
         f"    primer ping {primero} ms, mediana del resto {mediana} ms\n")
    return [
        fila("decision_por_flujo", "decisiones para 30 pings ida y vuelta", len(decisiones),
             "4 (una por sentido en cada switch de acceso) y clase tiempo_real", si(ok),
             variante="prioridad", clase="tiempo_real", cola=emp.colas.pol.cola("tiempo_real")),
        fila("decision_por_flujo", "packet-in en switches de acceso",
             despues["packet_in_acceso"] - antes["packet_in_acceso"], variante="prioridad"),
        fila("decision_por_flujo", "primer ping (ms)", primero, variante="prioridad"),
        fila("decision_por_flujo", "mediana del resto de pings (ms)", mediana, variante="prioridad"),
    ]


# ---------------- 2 y 3. cada clase a su cola, y la prioridad se nota ----------------
def bytes_por_clase(db, sede, desde, hasta):
    con = sqlite3.connect(db)
    filas = con.execute("SELECT clase, SUM(bytes) FROM flujos WHERE sede_id = ? AND ts > ? AND ts <= ? "
                        "GROUP BY clase", (sede, desde, hasta)).fetchall()
    con.close()
    return dict(filas)


def prueba_colas_y_prioridad(emp, gen, sala, db, intervalo, datos):
    from mininet.log import info
    import medicion as m
    pol = emp.colas.pol
    cuellos = [p for sw, p, _, _ in emp.puertos_acceso if sw == f"acc{sala}"]
    fase = next(f for f in plan_escenario(datos, ESCENARIO) if f["nombre"] == FASE)
    e = datos["escenarios"][ESCENARIO]
    filas, voz = [], {}
    for estrategia in ("fila_corta", "prioridad"):
        info(f"\n*** Pruebas 2 y 3 · fase '{FASE}' de {ESCENARIO} con {estrategia} ({fase['duracion_s']} s)\n")
        poner_estrategia(emp, estrategia)
        time.sleep(2)
        c0 = {p: emp.colas.contadores_colas(p) for p in cuellos}
        ts0 = time.time()
        reloj = RelojSimulado(e["inicio"]["dia"], e["inicio"]["hora"], datos["reloj"]["factor"])
        r, _, _ = correr_fase(emp, gen, sala, fase, datos.get("sondas", {}), m, reloj, ESCENARIO, estrategia)
        time.sleep(intervalo + 3)                   # el último sondeo de la telemetría
        c1 = {p: emp.colas.contadores_colas(p) for p in cuellos}
        ts1 = time.time()
        en_cola = {}
        for p in cuellos:
            for q, v in c1[p].items():
                a = en_cola.setdefault(q, {"bytes": 0, "descartes": 0})
                a["bytes"] += v["bytes"] - c0[p].get(q, {}).get("bytes", 0)
                a["descartes"] += v["descartes"] - c0[p].get(q, {}).get("descartes", 0)
        por_clase = bytes_por_clase(db, sala, ts0, ts1)
        total_colas = sum(v["bytes"] for v in en_cola.values()) or 1
        info(f"    {'Clase':12s} {'Cola':>4s} {'Telemetría':>11s} {'En la cola':>11s} {'Descartes':>9s}\n")
        for c in pol.clases:
            q, nombre = c["cola"], c["nombre"]
            tel_b, cola_b = por_clase.get(nombre, 0), en_cola.get(q, {}).get("bytes", 0)
            desc = en_cola.get(q, {}).get("descartes", 0)
            if estrategia == "prioridad":
                if tel_b > 100_000:
                    ok, criterio = 0.5 <= cola_b / tel_b <= 1.2, "su cola lleva 50-120 % de sus bytes (con descartes)"
                else:
                    ok, criterio = cola_b < 0.01 * total_colas, "sin tráfico de esta clase: cola casi vacía"
            else:
                ok, criterio = (cola_b >= 0.99 * total_colas) if q == 0 else (cola_b < 0.01 * total_colas), \
                    "sin clasificar: todo en la cola 0"
            info(f"    {nombre:12s} {q:>4} {tel_b / 1e6:8.2f} MB {cola_b / 1e6:8.2f} MB {desc:>9}  {si(ok)}\n")
            filas.append(fila("cada_clase_a_su_cola", "MB telemetría / MB en la cola",
                              f"{tel_b / 1e6:.2f} / {cola_b / 1e6:.2f} (descartes {desc})", criterio, si(ok),
                              variante=estrategia, clase=nombre, cola=q))
        voz[estrategia] = r
        for medida, clave in (("voz p95 peor sentido (ms)", "voz_lat95_ms"), ("voz MOS", "voz_mos"),
                              ("pagos p95 (ms)", "pagos_p95_ms"), ("uso bajada %", "uso_bajada_pct"),
                              ("uso subida %", "uso_subida_pct")):
            filas.append(fila("prioridad_se_nota", medida, r.get(clave), variante=estrategia))
        info(f"    voz p95 {r.get('voz_lat95_ms')} ms, MOS {r.get('voz_mos')}, pagos p95 "
             f"{r.get('pagos_p95_ms')} ms, uso {r.get('uso_bajada_pct')} / {r.get('uso_subida_pct')} %\n")
    fc, pr = voz["fila_corta"], voz["prioridad"]
    mejora = (pr.get("cumple_voz") == "sí" and pr.get("voz_lat95_ms") is not None
              and fc.get("voz_lat95_ms") is not None and pr["voz_lat95_ms"] <= fc["voz_lat95_ms"])
    filas.append(fila("prioridad_se_nota", "voz con prioridad cumple y no empeora",
                      f"{fc.get('voz_lat95_ms')} -> {pr.get('voz_lat95_ms')} ms",
                      "cumple objetivos de voz y p95 <= el de fila_corta", si(mejora), variante="comparación"))
    return filas


# ---------------- 4. las reglas vencen ----------------
def reglas_por_flujo(switch):
    r = subprocess.run(["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", switch, "cookie=0x16/-1"],
                       capture_output=True, text=True)
    return sum(1 for linea in r.stdout.splitlines() if "cookie=0x16" in linea)


def prueba_vencimiento(sala, idle, intervalo):
    from mininet.log import info
    sw = f"acc{sala}"
    antes = reglas_por_flujo(sw)
    espera = idle + intervalo + 3
    info(f"\n*** Prueba 4 · vencimiento: {antes} reglas por flujo en {sw}; esperando {espera} s sin tráfico\n")
    time.sleep(espera)
    despues = reglas_por_flujo(sw)
    info(f"    quedan {despues} reglas por flujo en {sw}\n")
    return [fila("vencimiento", f"reglas por flujo en {sw} (antes / después de {espera} s)",
                 f"{antes} / {despues}", f"0 después de idle_timeout ({idle} s)", si(despues == 0),
                 variante="prioridad")]


def tiempos_decision(db, desde):
    con = sqlite3.connect(db)
    ms = [x for (x,) in con.execute("SELECT ms FROM decisiones WHERE ts >= ?", (desde,)).fetchall()]
    con.close()
    p50, p95 = percentil(ms, 50), percentil(ms, 95)
    return ms, [fila("tiempo_de_decision", "decisiones / p50 / p95 / máx (ms)",
                     f"{len(ms)} / {p50} / {p95} / {max(ms) if ms else None}",
                     f"p95 < {OBJETIVO_DECISION_MS} ms", si(ms and p95 < OBJETIVO_DECISION_MS),
                     variante="todas")]


def main():
    p = argparse.ArgumentParser(description="Cada flujo a su cola en tiempo real (PCIII-19)")
    p.add_argument("--sala", type=int, default=1, choices=[1, 2, 3, 4])
    p.add_argument("--datapath", choices=("kernel", "user"), default="kernel")
    args = p.parse_args()
    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo")
    from mininet.log import info, setLogLevel
    from empresa_xyz import AVISO_RYU, CONFIG_DEFECTO, EmpresaXYZ, controlador_activo
    if not controlador_activo():
        sys.exit(AVISO_RYU.format(ip="127.0.0.1", puerto=6633))
    if not api.disponible():
        sys.exit(api.AVISO.format(url=api.URL))

    cfg_ctl = leer_config()
    db, intervalo, idle = cfg_ctl["base_datos"], cfg_ctl["intervalo_s"], cfg_ctl["idle_timeout_s"]
    perfiles = cargar_perfiles()
    datos = cargar_escenarios(perfiles=perfiles)
    setLogLevel("info")
    with open(CONFIG_DEFECTO) as f:
        cfg = yaml.safe_load(f)
    emp = EmpresaXYZ(cfg, datapath=args.datapath)
    emp.construir()
    emp.net.start()
    filas, inicio = [], time.time()
    fecha = datetime.datetime.now().isoformat(timespec="seconds")
    gen = None
    try:
        emp.configurar(estrategia="colas")
        info("*** Esperando 8 s a que los switches se conecten a Ryu\n")
        time.sleep(8)
        gen = Generador(emp.net, emp.inventario, semilla=7, perfiles=perfiles)
        gen.levantar_servidores(duracion=900)
        s = f"sa{args.sala}"
        for a, b in ((f"{s}tel", "ofpbx"), (f"{s}pos1", "inetpago1"), (f"{s}srv", "ofbak")):
            emp.net.get(a).cmd(f"ping -c2 -W2 {emp.net.get(b).IP()}")
        filas += prueba_decision(emp, args.sala, db, intervalo)
        filas += prueba_colas_y_prioridad(emp, gen, args.sala, db, intervalo, datos)
        gen.detener()
        filas += prueba_vencimiento(args.sala, idle, intervalo)
        ms, f_ms = tiempos_decision(db, inicio)
        filas += f_ms
    finally:
        if gen:
            gen.detener()
        try:
            api.poner_clasificador("ninguno")
        except api.ErrorApi:
            pass
        emp.limpiar()
        emp.net.stop()
        if filas:
            for f in filas:
                f.update(fecha=fecha, sala=args.sala)
            os.makedirs(os.path.dirname(CSV), exist_ok=True)
            nuevo = not os.path.exists(CSV)
            with open(CSV, "a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=CAMPOS, extrasaction="ignore")
                if nuevo:
                    w.writeheader()
                w.writerows(filas)
    resumen(filas)
    info(f"\n*** Resultados agregados a {CSV}\n")


def resumen(filas):
    from mininet.log import info
    info("\n    Resumen PCIII-19\n")
    for f in filas:
        if f["cumple"] != "-":
            extra = f" [{f.get('variante')}{' · ' + f['clase'] if f.get('clase') else ''}]"
            info(f"    {f['cumple']:3s} {f['prueba']:22s} {f['medida']}: {f['valor']}{extra}\n")


if __name__ == "__main__":
    main()
