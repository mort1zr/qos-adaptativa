#!/usr/bin/env python3
"""
Escenarios reproducibles de la empresa (historia PCIII-18).

  python3 escenarios/escenario.py --listar
  python3 escenarios/escenario.py --plan --nombre sorteo --ruido 0.1
  sudo python3 escenarios/escenario.py --nombre sorteo --estrategia fila_corta --sala 1
  sudo python3 escenarios/escenario.py --nombre apertura,respaldo_en_atencion --estrategia prioridad,estatica
  sudo python3 escenarios/escenario.py --todos --estrategia sin_qos,fila_corta,prioridad --sala 4

Levanta la red una sola vez y, para cada estrategia y cada escenario, recorre
sus fases: genera el tráfico de los perfiles (trafico/), mide con sondas la
voz, la videollamada, los pagos y la carga de páginas web, lee el uso del
enlace de la sala, mide el goodput del respaldo y de las descargas (lo que les
llega de verdad: lo que pierde lo "masivo" al priorizar) y, de la telemetría,
lo que cada clase ofreció al enlace. El reloj simulado se
publica en datos/reloj.json y cada fase queda registrada en datos/contexto.csv
(para unir la telemetría con el escenario, la hora y la estrategia).

Estrategias:
  sin_qos     una cola, FIFO larga: red sin gestionar
  fila_corta  6 colas, todo en "masivo", fila corta: la estrategia de control
  prioridad   6 colas y el controlador manda cada flujo a la cola de su clase
              (set_queue, PCIII-19) reconociéndolo por la tabla de destinos
              (clasificador 'destino', PCIII-20); las tasas no cambian
  estatica    lo mismo que prioridad + los techos por horario de
              politicas/horario.yaml, según la hora simulada (PCIII-21)
'ia' llega en los Sprints 4-5.
La estrategia también fija el clasificador de Ryu, por su API REST.

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

from escenarios.operador import Operador, condiciones  # noqa: E402
from escenarios.operador import validar as validar_enlace  # noqa: E402
from escenarios.reloj import DIAS, RelojSimulado, normalizar_dia  # noqa: E402
from controlador import api  # noqa: E402
from trafico.generador import APLICACIONES, Generador, cargar_perfiles  # noqa: E402

ESCENARIOS = os.path.join(AQUI, "escenarios.yaml")
CSV = os.path.join(RAIZ, "experimentos", "resultados", "escenarios.csv")
CONTEXTO = os.path.join(RAIZ, "datos", "contexto.csv")
ESTRATEGIAS = {"sin_qos": "sin_qos", "fila_corta": "colas", "prioridad": "colas",
               "estatica": "colas"}                                            # -> colas de la topología
CLASIFICADOR = {"sin_qos": "ninguno", "fila_corta": "ninguno", "prioridad": "destino",
                "estatica": "destino"}                                         # -> clasificador de Ryu
CON_HORARIO = {"estatica"}                                                     # -> techos por horario
FUTURAS = {"ia": "los Sprints 4 y 5"}
PUERTO_VOZ = 5001
PUERTO_VIDEO = 5002
SONDAS = {"voz", "video", "pagos", "web"}
CPU_MAXIMA_PCT = 90      # sobre esto, la fase se marca inválida: la VM fue el cuello de botella
CLASES_TELEMETRIA = ("tiempo_real", "critico", "negocio", "vigilancia", "masivo", "restringido")


class EscenarioInvalido(ValueError):
    pass


def cargar_escenarios(ruta: str = ESCENARIOS, perfiles: dict = None) -> dict:
    with open(ruta) as f:
        datos = yaml.safe_load(f)
    nombres_perfiles = set((perfiles or cargar_perfiles())["perfiles"])
    errores = []
    if not datos.get("reloj", {}).get("factor", 0) > 0:
        errores.append("reloj.factor debe ser mayor que 0")
    for k in set(datos.get("sondas") or {}) - SONDAS:
        errores.append(f"sonda desconocida '{k}' (hay: {', '.join(sorted(SONDAS))})")
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
        for k in set(e.get("sondas") or {}) - SONDAS:
            errores.append(f"{nombre}: sonda desconocida '{k}'")
        for fase in e.get("fases") or []:
            errores += [f"{nombre}/{fase.get('nombre')}: {x}" for x in validar_enlace(fase.get("enlace"))]
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


def sondas_de(datos: dict, nombre: str) -> dict:
    """Sondas de un escenario: las generales, con lo que el escenario cambie
    (p. ej. la madrugada apaga la videollamada y la web: la sala está cerrada)."""
    sondas = dict(datos.get("sondas") or {})
    sondas.update(datos["escenarios"][nombre].get("sondas") or {})
    return {k: v for k, v in sondas.items() if v}


def plan_escenario(datos: dict, nombre: str, semilla: int = 7, ruido: float = 0.0,
                   escala: float = 1.0) -> list:
    """Fases con sus intensidades finales (con ruido reproducible). No toca la red."""
    if nombre not in datos["escenarios"]:
        raise EscenarioInvalido(f"escenario desconocido: {nombre} (hay: {', '.join(datos['escenarios'])})")
    rng = random.Random(f"{semilla}-{nombre}")
    fases = []
    for fase in datos["escenarios"][nombre]["fases"]:
        f = {"nombre": fase["nombre"], "duracion_s": max(10, round(fase["duracion_s"] * escala))}
        if fase.get("enlace"):
            f["enlace"] = dict(fase["enlace"])
        for lugar in ("sala", "oficina"):
            f[lugar] = {p: round(max(0.0, v * (1 + rng.uniform(-ruido, ruido))), 3) if ruido else v
                        for p, v in sorted((fase.get(lugar) or {}).items())}
        fases.append(f)
    return fases


# ---------------- ejecución en la red ----------------
def poner_estrategia(emp, estrategia, cliente=api, avisar=print):
    """Colas de los enlaces de acceso y clasificador de Ryu de una estrategia."""
    emp.colas.hoja = "fifo" if estrategia == "sin_qos" else "pfifo:64"
    for _, puerto, mbps, _ in emp.puertos_acceso:
        if ESTRATEGIAS[estrategia] == "colas":
            emp.colas.aplicar(puerto, mbps)
        else:
            emp.colas.linea_base(puerto, mbps)
    clasificador = CLASIFICADOR[estrategia]
    try:
        cliente.poner_clasificador(clasificador)
    except cliente.ErrorApi:
        if clasificador != "ninguno":
            raise
        avisar("    (aviso: sin la API de Ryu no se pudo confirmar el clasificador 'ninguno')")


def cpu_jiffies():
    """(ocupado, total) de la CPU de la máquina, de /proc/stat (todas las CPU)."""
    try:
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
    except (OSError, ValueError):
        return None
    inactivo = v[3] + (v[4] if len(v) > 4 else 0)          # idle + iowait
    return sum(v) - inactivo, sum(v)


def cpu_pct(antes, despues):
    if not antes or not despues or despues[1] <= antes[1]:
        return None
    return round(100 * (despues[0] - antes[0]) / (despues[1] - antes[1]), 1)


def validez(cpu):
    """Una fase es válida si la VM no fue el cuello de botella (lo medido es la red, no la CPU)."""
    if cpu is not None and cpu >= CPU_MAXIMA_PCT:
        return f"no (CPU {cpu:.0f} %)"
    return "sí"


def sonda_udp(m, a, b, puerto, perfil, dur, sonda_dur):
    """Sonda UDP en los dos sentidos entre a y b: (receptores, emisores)."""
    rx = {"subida": m.receptor_udp(b, puerto, dur + 30), "bajada": m.receptor_udp(a, puerto, dur + 30)}
    return rx, (a, b, puerto, perfil, sonda_dur)


def evaluar_udp(m, rx, prefijo, con_mos):
    """Columnas de una sonda UDP de dos sentidos; se califica por el peor sentido."""
    fila, sentidos = {}, {}
    for sentido, (_, ruta) in rx.items():
        r = m.resultado_udp(ruta)
        if "error" in r:
            r = {"latencia_p95_ms": None, "jitter_ms": None, "perdida_pct": 100.0}
        if con_mos:
            r["mos"] = m.mos(r["latencia_p95_ms"], r["jitter_ms"], r["perdida_pct"]) \
                if r["latencia_p95_ms"] is not None else 1.0
        sentidos[sentido] = r
        fila.update({f"{prefijo}_{sentido}_lat95_ms": r["latencia_p95_ms"],
                     f"{prefijo}_{sentido}_jitter_ms": r["jitter_ms"],
                     f"{prefijo}_{sentido}_perdida_pct": r["perdida_pct"]})
        if con_mos:
            fila[f"{prefijo}_{sentido}_mos"] = r["mos"]
    fila.update({f"{prefijo}_lat95_ms": max((r["latencia_p95_ms"] or 0) for r in sentidos.values()) or None,
                 f"{prefijo}_jitter_ms": max((r["jitter_ms"] or 0) for r in sentidos.values()),
                 f"{prefijo}_perdida_pct": max(r["perdida_pct"] for r in sentidos.values())})
    if con_mos:
        fila[f"{prefijo}_mos"] = min(r["mos"] for r in sentidos.values())
    if any(r["latencia_p95_ms"] is None for r in sentidos.values()):
        fila[f"cumple_{prefijo}"] = "no (sin datos)"
    else:
        fila[f"cumple_{prefijo}"] = m.evaluar({"latencia_p95_ms": fila[f"{prefijo}_lat95_ms"],
                                               "jitter_ms": fila[f"{prefijo}_jitter_ms"],
                                               "perdida_pct": fila[f"{prefijo}_perdida_pct"],
                                               "mos": fila.get(f"{prefijo}_mos")})
    return fila


def leer_json(ruta, vacio):
    try:
        with open(ruta) as f:
            return json.load(f)
    except (OSError, ValueError):
        return vacio


def metricas_telemetria(db: str, sede: int, desde: float, hasta: float, segundos: float) -> dict:
    """Lo que cada clase OFRECIÓ al enlace de la sala (Mbps, los dos sentidos), según la
    telemetría del controlador. Se cuenta al entrar al switch, antes de las colas:
    incluye lo que después se descarta y se retransmite (lo que LLEGA se mide aparte,
    con el goodput de las aplicaciones). La clase es la etiqueta de la política, la
    misma en todas las estrategias, para comparar."""
    import sqlite3
    try:
        con = sqlite3.connect(db)
        por_clase = dict(con.execute("SELECT clase, SUM(bytes) FROM flujos WHERE sede_id = ? AND ts > ? "
                                     "AND ts <= ? GROUP BY clase", (sede, desde, hasta)).fetchall())
        con.close()
    except sqlite3.Error:
        return {}
    return {f"ofrecido_{c}_mbps": round((por_clase.get(c) or 0) * 8 / segundos / 1e6, 2)
            for c in CLASES_TELEMETRIA}


def goodput_masivo(g: dict) -> dict:
    """Columnas del goodput del respaldo y de las descargas (None si no hubo en la fase)."""
    fila = {"respaldo_goodput_mbps": g.get("respaldo"), "descargas_goodput_mbps": g.get("descargas")}
    r = fila["respaldo_goodput_mbps"]
    # A este ritmo, ¿cuánto tardaría 1 GB de respaldo? (8000 megabits)
    fila["respaldo_1gb_min"] = round(8000 / r / 60, 1) if r and r >= 0.1 else None
    return fila


def correr_fase(emp, gen, sala, fase, sondas, m, reloj, nombre, estrategia, telemetria=None, objetivos=None,
                operador=None):
    """Corre una fase: tráfico de los perfiles + sondas. Devuelve (fila, t0, t1).
    telemetria = (ruta de la base, intervalo_s): espera el último sondeo y agrega
    lo que obtuvo cada clase."""
    objetivos = objetivos or {}
    net, s, dur = emp.net, f"sa{sala}", fase["duracion_s"]
    cuellos = {sentido: p for sw, p, _, sentido in emp.puertos_acceso if sw == f"acc{sala}"}
    capacidad = next(mb for sw, _, mb, _ in emp.puertos_acceso if sw == f"acc{sala}")
    enlace = condiciones(fase.get("enlace"))
    if operador:
        operador.aplicar(sala, fase.get("enlace"))     # antes del tráfico: la fase entera con esas condiciones
    t0 = time.time()
    reloj.guardar(nombre, fase["nombre"], estrategia=estrategia, sala=sala)
    hora = reloj.describir(t0)
    gen.medir = {"respaldo", "descargas"}
    gen.goodput()                                      # descarta lo pendiente de otra fase
    for perfil, i in fase["sala"].items():
        gen.iniciar(perfil, sala, dur, i)
    for perfil, i in fase["oficina"].items():
        gen.iniciar(perfil, 0, dur, i)

    # Sondas: arrancan 2 s después y terminan 2 s antes, para medir la fase "llena".
    sonda_dur = max(5, dur - 4)
    udp = {}     # nombre -> (receptores, (a, b, puerto, perfil, duración))
    if sondas.get("voz"):
        # Llamada entre el teléfono de la sala y la central, en los dos sentidos.
        udp["voz"] = sonda_udp(m, net.get(f"{s}tel"), net.get("ofpbx"), PUERTO_VOZ, m.VOIP, dur, sonda_dur)
    if sondas.get("video"):
        # Videollamada de la caja con Teams, en los dos sentidos.
        v = sondas["video"] if isinstance(sondas["video"], dict) else {}
        perfil = {"pps": v.get("pps", m.VIDEO["pps"]), "largo": v.get("largo", m.VIDEO["largo"])}
        udp["video"] = sonda_udp(m, net.get(f"{s}caja"), net.get("inetvc"), PUERTO_VIDEO, perfil, dur, sonda_dur)
    rutas = {}
    for k in ("pagos", "web"):
        if sondas.get(k):
            rutas[k] = f"/tmp/qos_mediciones/{k}_{s}.json"
            os.makedirs(os.path.dirname(rutas[k]), exist_ok=True)
            if os.path.exists(rutas[k]):
                os.remove(rutas[k])
    time.sleep(2)
    b0 = {k: emp.colas.bytes_enviados(p) for k, p in cuellos.items()}
    tb0, c0 = time.time(), cpu_jiffies()
    procesos = []
    for rx, (a, b, puerto, perfil, sd) in udp.values():
        procesos.append(m.emisor_udp(a, b.IP(), puerto, perfil, sd))
        procesos.append(m.emisor_udp(b, a.IP(), puerto, perfil, sd))

    def transacciones(origen, destino, cfg, ruta):
        return net.get(origen).popen(
            [gen.python, APLICACIONES, "cliente", "--destino", net.get(destino).IP(), "--puerto", "443",
             "--patron", "transacciones", "--periodo", str(cfg["periodo_s"]), "--nueva-conexion",
             "--peticion", str(cfg["peticion"]), "--respuesta", str(cfg["respuesta"]),
             "--variacion", "0", "--duracion", str(sonda_dur), "--salida", ruta],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if "pagos" in rutas:
        procesos.append(transacciones(f"{s}pos1", "inetpago1", sondas["pagos"], rutas["pagos"]))
    if "web" in rutas:
        # Una página web desde la caja cada pocos segundos: lo "masivo" que sí ve una persona.
        procesos.append(transacciones(f"{s}caja", "inetweb", sondas["web"], rutas["web"]))
    restante = dur - (time.time() - t0)
    time.sleep(max(0, restante - 2))
    b1 = {k: emp.colas.bytes_enviados(p) for k, p in cuellos.items()}
    tb1, c1 = time.time(), cpu_jiffies()
    for p in procesos:
        m.esperar(p, limite=20)
    for rx, _ in udp.values():
        for proc, _ in rx.values():
            m.esperar(proc, limite=15)
    gen.esperar(limite=15)
    gen.procesos = [x for x in gen.procesos if "servidor" in x[0]]
    t1 = time.time()
    goodput = gen.goodput()

    uso = {k: 100 * (b1[k] - b0[k]) * 8 / (tb1 - tb0) / 1e6 / capacidad for k in cuellos}
    fila = {"fase": fase["nombre"], "hora_simulada": hora, "duracion_s": dur,
            "uso_bajada_pct": round(uso["bajada"], 1), "uso_subida_pct": round(uso["subida"], 1),
            "enlace_capacidad_pct": enlace["capacidad_pct"], "enlace_perdida_pct": enlace["perdida_pct"],
            "enlace_retardo_ms": enlace["retardo_ms"], "cpu_pct": cpu_pct(c0, c1)}
    fila["valida"] = validez(fila["cpu_pct"])
    if "voz" in udp:
        fila.update(evaluar_udp(m, udp["voz"][0], "voz", con_mos=True))
    if "video" in udp:
        fila.update(evaluar_udp(m, udp["video"][0], "video", con_mos=False))
    if "pagos" in rutas:
        rp = leer_json(rutas["pagos"], {"transacciones": 0, "errores": 1})
        fila.update(pagos_n=rp.get("transacciones", 0), pagos_errores=rp.get("errores", 0),
                    pagos_p95_ms=rp.get("p95_ms"))
    if "web" in rutas:
        rw = leer_json(rutas["web"], {"transacciones": 0, "errores": 1})
        fila.update(web_n=rw.get("transacciones", 0), web_errores=rw.get("errores", 0),
                    web_p50_ms=rw.get("p50_ms"), web_p95_ms=rw.get("p95_ms"))
        objetivo = objetivos.get("web_p95_ms", 3000)
        ok = fila["web_n"] > 0 and fila["web_errores"] == 0 and (fila["web_p95_ms"] or 1e9) <= objetivo
        fila["cumple_web"] = "sí" if ok else "no"
    fila.update(goodput_masivo(goodput))
    if telemetria:
        db, intervalo = telemetria
        # Un sondeo más: los últimos bytes de cada flujo llegan con él. De paso, las
        # colas se vacían antes de la fase siguiente.
        time.sleep(intervalo + 1)
        fila.update(metricas_telemetria(db, sala, t0, time.time(), dur))
    return fila, t0, t1


def devolver_al_usuario(ruta):
    """Los scripts corren con sudo: el archivo que crean queda de root, y después los
    que corren sin sudo (análisis, consultas, git) no pueden escribirlo. Se lo
    devuelve al usuario que llamó a sudo."""
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid and gid and os.geteuid() == 0 and os.path.exists(ruta):
        try:
            os.chown(ruta, int(uid), int(gid))
            os.chown(os.path.dirname(ruta), int(uid), int(gid))
        except OSError:
            pass


def guardar_csv(ruta, filas):
    """Agrega filas al CSV. Si traen columnas nuevas, reescribe el archivo con el
    encabezado ampliado (las filas viejas quedan con esas columnas vacías), en vez
    de dejar columnas corridas."""
    if not filas:
        return
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    campos = []
    for f in filas:
        campos += [k for k in f if k not in campos]
    previas, cabecera = [], []
    if os.path.exists(ruta):
        with open(ruta, newline="") as fh:
            lector = csv.DictReader(fh)
            cabecera, previas = list(lector.fieldnames or []), list(lector)
    if cabecera and set(campos) <= set(cabecera):
        with open(ruta, "a", newline="") as fh:
            csv.DictWriter(fh, fieldnames=cabecera, extrasaction="ignore").writerows(filas)
        devolver_al_usuario(ruta)
        return
    campos = cabecera + [c for c in campos if c not in cabecera]
    with open(ruta, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(previas + filas)
    devolver_al_usuario(ruta)


def enlace_degradado(fila: dict) -> bool:
    return (float(fila.get("enlace_capacidad_pct") or 100) < 100 or float(fila.get("enlace_perdida_pct") or 0) > 0
            or float(fila.get("enlace_retardo_ms") or 0) > 0)


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
        fase_txt = f["fase"] + ("*" if enlace_degradado(f) else "")
        print(f"    {fase_txt:16s} {f['hora_simulada']:14s} "
              f"{fmt(f['uso_bajada_pct'], 0):>5s}/{fmt(f['uso_subida_pct'], 0):<4s} % "
              f"{voz:>16s} {fmt(f.get('voz_jitter_ms'), 2):>7s} "
              f"{fmt(f.get('voz_perdida_pct'), 2):>6s} {fmt(f.get('voz_mos'), 2):>5s} "
              f"{fmt(f.get('pagos_p95_ms'), 0):>7s} ms  {f.get('cumple_voz', '-')} / {f.get('cumple_pagos', '-')}")
    otras = [f for f in filas if any(k in f for k in ("video_lat95_ms", "web_p95_ms", "respaldo_1gb_min"))]
    actual = None
    for f in otras:
        if (f["escenario"], f["estrategia"]) != actual:
            actual = (f["escenario"], f["estrategia"])
            print(f"\n  {f['escenario']} · {f['estrategia']} · otras métricas")
            print(f"    {'Fase':16s} {'Video p95/pérd':>15s} {'Web p95':>8s} {'Respaldo':>9s} {'1 GB en':>8s} "
                  f"{'Descargas':>10s}   Ofrecido: {'T.real':>6s} {'Masivo':>7s} {'Restr.':>7s}  Cumple video / web")
        video = (f"{fmt(f.get('video_lat95_ms'), 0)} ms/{fmt(f.get('video_perdida_pct'), 1)}%"
                 if "video_lat95_ms" in f else "-")
        web = f"{fmt(f.get('web_p95_ms') / 1000 if f.get('web_p95_ms') else None, 1)} s" if "web_p95_ms" in f else "-"
        gb = f"{fmt(f.get('respaldo_1gb_min'), 0)} min" if f.get("respaldo_1gb_min") else "-"
        fase_txt = f["fase"] + ("*" if enlace_degradado(f) else "")
        print(f"    {fase_txt:16s} {video:>15s} {web:>8s} {fmt(f.get('respaldo_goodput_mbps'), 1):>5s} Mb {gb:>8s} "
              f"{fmt(f.get('descargas_goodput_mbps'), 1):>6s} Mb             "
              f"{fmt(f.get('ofrecido_tiempo_real_mbps'), 1):>4s} Mb "
              f"{fmt(f.get('ofrecido_masivo_mbps'), 1):>4s} Mb {fmt(f.get('ofrecido_restringido_mbps'), 1):>4s} Mb  "
              f"{f.get('cumple_video', '-')} / {f.get('cumple_web', '-')}")
    print("\n    Voz y video: se miden en los dos sentidos; jitter, pérdida y MOS son los del peor.")
    if any(enlace_degradado(f) for f in filas):
        print("    * fase con el enlace del operador degradado (capacidad, pérdida o retardo: ver el CSV).")
    print("    Respaldo y descargas: goodput (lo que llegó a la aplicación); '1 GB en' = cuánto tardaría un "
          "respaldo de 1 GB a ese ritmo.\n    Ofrecido: lo que cada clase intentó pasar por el enlace de la sala "
          "(telemetría, los dos sentidos, incluye lo descartado y retransmitido).")


def main():
    p = argparse.ArgumentParser(description="Escenarios reproducibles de la empresa")
    p.add_argument("--nombre", help="escenario a correr (o varios separados por coma)")
    p.add_argument("--todos", action="store_true", help="todos los escenarios, uno tras otro")
    p.add_argument("--estrategia", default="fila_corta",
                   help="sin_qos, fila_corta, prioridad, estatica (o varias separadas por coma)")
    p.add_argument("--sala", type=int, default=1, choices=[1, 2, 3, 4])
    p.add_argument("--semilla", type=int, default=7)
    p.add_argument("--ruido", type=float, default=0.0, help="variación aleatoria de las intensidades (0.1 = ±10 %%)")
    p.add_argument("--escala", type=float, default=1.0, help="multiplica la duración de las fases (pruebas rápidas)")
    p.add_argument("--salida", help="CSV separado para la demo; conserva la salida habitual si se omite")
    p.add_argument("--progreso", help="publicar fases en un archivo JSON")
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
    if args.todos:
        nombres = list(datos["escenarios"])
    elif args.nombre:
        nombres = [n.strip() for n in args.nombre.split(",") if n.strip()]
    else:
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
                enlace = f"  enlace del operador: {f['enlace']}" if f.get("enlace") else ""
                print(f"    {f['nombre']:16s} {f['duracion_s']:>4} s  sala: {f['sala']}{enlace}")
                if f["oficina"]:
                    print(f"    {'':16s} {'':>4}    oficina: {f['oficina']}")
        return

    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo (levanta la red de Mininet)")
    filas, contexto = [], []
    salida = os.path.abspath(args.salida) if args.salida else CSV
    ruta_contexto = os.path.splitext(salida)[0] + "_contexto.csv" if args.salida else CONTEXTO
    progreso = None
    if args.progreso:
        from escenarios.progreso import Progreso
        progreso = Progreso(args.progreso)
        from politicas.cargador import cargar
        o = cargar().objetivos
        progreso.iniciar(datos, planes, estrategias,
                         {"escenarios": nombres, "estrategias": estrategias, "sala": args.sala,
                          "semilla": args.semilla, "escala": args.escala},
                         {"voz_lat95_ms": o["latencia_p95_ms"], "voz_mos": o["mos_min"],
                          **datos.get("objetivos", {})})

    def guardar_escenario(f, c):
        filas.extend(f)
        contexto.extend(c)
    if progreso:
        import signal

        def detener_demo(signum, frame):
            raise KeyboardInterrupt("Demo cancelada")

        signal.signal(signal.SIGTERM, detener_demo)
    try:
        ejecutar(datos, perfiles, nombres, estrategias, args.sala, args.semilla, args.ruido, args.escala,
                 args.datapath, al_terminar=guardar_escenario, progreso=progreso)
    except BaseException as exc:
        if progreso:
            progreso.finalizar("cancelado" if isinstance(exc, KeyboardInterrupt) else "fallido", str(exc))
        raise
    else:
        if progreso:
            progreso.finalizar()
    finally:
        guardar_csv(salida, filas)
        guardar_csv(ruta_contexto, contexto)
    imprimir(filas)
    imprimir_objetivos(datos)
    print(f"*** Resultados agregados a {salida}\n*** Contexto de cada fase (para la IA) en {ruta_contexto}")


def imprimir_objetivos(datos):
    import medicion as m
    o = datos.get("objetivos", {})
    print(f"\n    Objetivos: voz (jitter < {m.OBJETIVOS['jitter_ms']:g} ms, pérdida < {m.OBJETIVOS['perdida_pct']:g} %, "
          f"latencia p95 < {m.OBJETIVOS['latencia_ms']:g} ms, MOS >= {m.OBJETIVOS['mos']:g}); "
          f"pagos p95 <= {o.get('pagos_p95_ms', 500)} ms y sin errores; video (jitter, pérdida, latencia p95 como "
          f"la voz, sin MOS); web p95 <= {o.get('web_p95_ms', 3000) / 1000:g} s.")


def ejecutar(datos, perfiles, nombres, estrategias, sala, semilla=7, ruido=0.0, escala=1.0, datapath="kernel",
             al_terminar=None, extra=None, progreso=None):
    """Levanta la red, corre los escenarios 'nombres' con cada estrategia en la sala y la
    apaga. Al terminar cada escenario llama a al_terminar(filas, contexto) con sus filas
    (así una corrida larga guarda lo hecho aunque después se interrumpa). 'extra' son
    columnas que se agregan a cada fila (p. ej. el nombre de la campaña)."""
    from mininet.log import info, setLogLevel
    from empresa_xyz import AVISO_RYU, CONFIG_DEFECTO, EmpresaXYZ, controlador_activo
    import medicion as m
    if not controlador_activo():
        raise RuntimeError(AVISO_RYU.format(ip="127.0.0.1", puerto=6633))
    if any(CLASIFICADOR[e] != "ninguno" for e in estrategias) and not api.disponible():
        raise RuntimeError(api.AVISO.format(url=api.URL))
    extra = extra or {}
    planes = {n: plan_escenario(datos, n, semilla, ruido, escala) for n in nombres}
    setLogLevel("info")
    with open(CONFIG_DEFECTO) as f:
        cfg = yaml.safe_load(f)
    emp = EmpresaXYZ(cfg, datapath=datapath)
    fecha = datetime.datetime.now().isoformat(timespec="seconds")
    objetivo_pagos = datos.get("objetivos", {}).get("pagos_p95_ms", 500)
    from controlador.telemetria import leer_config
    cfg_tel = leer_config()
    telemetria = (cfg_tel["base_datos"], cfg_tel["intervalo_s"])
    gen = operador = motor = None
    try:
        emp.construir()
        emp.net.start()
        emp.configurar(estrategia=ESTRATEGIAS[estrategias[0]])
        operador = Operador.de_empresa(emp, avisar=lambda t: info(t + "\n"))
        info("*** Esperando 8 s a que los switches se conecten a Ryu\n")
        time.sleep(8)
        gen = Generador(emp.net, emp.inventario, semilla=semilla, perfiles=perfiles)
        total = sum(f["duracion_s"] + 15 for fs in planes.values() for f in fs) * len(estrategias)
        gen.levantar_servidores(duracion=total + 600)
        s = f"sa{sala}"
        for a, b in ((f"{s}tel", "ofpbx"), (f"{s}pos1", "inetpago1"), (f"{s}cli1", "inetstr")):
            emp.net.get(a).cmd(f"ping -c2 -W2 {emp.net.get(b).IP()}")
        info(f"*** {len(nombres)} escenario(s) x {len(estrategias)} estrategia(s) en la Sala {sala}, "
             f"semilla {semilla}: unos {total // 60 + 1} min\n")
        for estrategia in estrategias:
            poner_estrategia(emp, estrategia)
            motor = None
            if estrategia in CON_HORARIO:
                from controlador.estatica import QoSEstatica, cargar_horario
                motor = QoSEstatica(emp.colas, [(p, mb) for _, p, mb, _ in emp.puertos_acceso],
                                    cargar_horario(emp.colas.pol), avisar=lambda t: info(t + "\n"))
            time.sleep(2)
            for nombre in nombres:
                e = datos["escenarios"][nombre]
                reloj = RelojSimulado(e["inicio"]["dia"], e["inicio"]["hora"], datos["reloj"]["factor"])
                info(f"\n*** {nombre} · {estrategia} · empieza {reloj.describir()} (simulado)\n")
                if motor:
                    # La franja del inicio se aplica ANTES del tráfico; los cambios dentro
                    # del escenario (p. ej. las 08:00 de la apertura) los aplica el hilo.
                    reloj.guardar(nombre, planes[nombre][0]["nombre"], estrategia=estrategia, sala=sala)
                    motor.paso()
                    if not motor._hilo:
                        motor.iniciar()
                filas, contexto = [], []
                for fase in planes[nombre]:
                    info(f"    fase {fase['nombre']} ({fase['duracion_s']} s, {reloj.describir()})\n")
                    if progreso:
                        progreso.empezar_fase(nombre, estrategia, fase["nombre"], reloj.describir())
                    franja_ini = motor.actual if motor else None
                    fila, t0, t1 = correr_fase(emp, gen, sala, fase, sondas_de(datos, nombre), m,
                                               reloj, nombre, estrategia, telemetria=telemetria,
                                               objetivos=datos.get("objetivos", {}), operador=operador)
                    if motor:
                        fila["franja"] = (franja_ini if franja_ini == motor.actual
                                          else f"{franja_ini}->{motor.actual}")
                    if "pagos_p95_ms" in fila:
                        ok = (fila["pagos_n"] > 0 and fila["pagos_errores"] == 0
                              and fila["pagos_p95_ms"] is not None and fila["pagos_p95_ms"] <= objetivo_pagos)
                        fila["cumple_pagos"] = "sí" if ok else "no"
                    if progreso:
                        progreso.terminar_fase(nombre, estrategia, fase["nombre"], fila)
                    filas.append({**extra, "fecha": fecha, "escenario": nombre, "estrategia": estrategia,
                                  "sala": sala, "semilla": semilla, "ruido": ruido, **fila})
                    contexto.append({**extra, "inicio_real": round(t0, 3), "fin_real": round(t1, 3),
                                     "escenario": nombre, "estrategia": estrategia, "sala": sala,
                                     "fase": fase["nombre"],
                                     "inicio_simulado": reloj.simulado(t0).isoformat(timespec="minutes"),
                                     "factor": reloj.factor, "semilla": semilla, "ruido": ruido,
                                     "franja": fila.get("franja", "")})
                if al_terminar:
                    al_terminar(filas, contexto)
            if motor:
                motor.detener()
                motor = None
    finally:
        if motor:
            motor.detener()
        if gen:
            gen.detener()
        if operador:
            try:
                operador.normalizar()
            except Exception:
                pass
        emp.limpiar()
        emp.net.stop()


if __name__ == "__main__":
    main()
