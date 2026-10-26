#!/usr/bin/env python3
"""
Análisis de una campaña de comparación (PCIII-23).

  python3 experimentos/analisis.py --campana pciii23
  python3 experimentos/analisis.py --campana pciii23 --comparar prioridad:estatica

Lee experimentos/resultados/comparacion.csv, deja fuera las fases inválidas (la
CPU de la VM fue el cuello de botella) y las listadas en
experimentos/resultados/descartes.yaml, y calcula:

  1. Por sala y estrategia: qué % de las fases cumple los objetivos (voz, video,
     pagos, web y todos a la vez) y el goodput del respaldo y de las descargas.
  2. Por sala, escenario, fase y estrategia: promedio e intervalo del 95 % de cada
     métrica (CSV analisis_<campana>.csv).
  3. Comparaciones en pares: la misma sala, escenario, fase y semilla con dos
     estrategias. Mediana de la diferencia y prueba de Wilcoxon (todas las fases
     juntas: por escenario hay pocas repeticiones para una prueba).

El resumen legible queda en experimentos/resultados/analisis_<campana>.md.
No necesita sudo ni la red.
"""
import argparse
import csv
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)

import yaml  # noqa: E402

from escenarios.estadistica import MIN_PARES, media_ic, mediana, wilcoxon  # noqa: E402

RESULTADOS = os.path.join(AQUI, "resultados")
CSV = os.path.join(RESULTADOS, "comparacion.csv")
DESCARTES = os.path.join(RESULTADOS, "descartes.yaml")
ORDEN = ["sin_qos", "fila_corta", "prioridad", "estatica", "ia"]
# (columna, nombre, cuál es mejor)
METRICAS = [("voz_lat95_ms", "Voz p95 (ms)", "menor"), ("voz_mos", "Voz MOS", "mayor"),
            ("video_lat95_ms", "Video p95 (ms)", "menor"), ("pagos_p95_ms", "Pagos p95 (ms)", "menor"),
            ("web_p95_ms", "Web p95 (ms)", "menor"),
            ("respaldo_goodput_mbps", "Respaldo (Mbps)", "mayor"),
            ("descargas_goodput_mbps", "Descargas (Mbps)", "mayor"),
            ("uso_bajada_pct", "Uso bajada (%)", "mayor"), ("uso_subida_pct", "Uso subida (%)", "mayor")]
CUMPLE = [("cumple_voz", "voz"), ("cumple_video", "video"), ("cumple_pagos", "pagos"), ("cumple_web", "web")]
COMPARAR = "sin_qos:fila_corta,fila_corta:prioridad,prioridad:estatica"


def numero(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except ValueError:
        return None


def cargar(campana, ruta=CSV, descartes=DESCARTES):
    """(filas válidas, cuántas se dejaron fuera y por qué)."""
    with open(ruta, newline="") as f:
        filas = [r for r in csv.DictReader(f) if r.get("campana") == campana]
    reglas = []
    if os.path.exists(descartes):
        with open(descartes) as f:
            for d in (yaml.safe_load(f) or {}).get("descartes") or []:
                if d.get("archivo") == os.path.basename(ruta):
                    reglas.append({k: str(v) for k, v in d.items() if k not in ("archivo", "motivo")})
    validas, fuera = [], {"inválidas (CPU)": 0, "descartadas": 0}
    for r in filas:
        if any(all(r.get(k) == v for k, v in regla.items()) for regla in reglas):
            fuera["descartadas"] += 1
        elif r.get("valida", "sí") != "sí":
            fuera["inválidas (CPU)"] += 1
        else:
            validas.append(r)
    return validas, fuera


def orden_estrategias(filas):
    presentes = {r["estrategia"] for r in filas}
    return [e for e in ORDEN if e in presentes] + sorted(presentes - set(ORDEN))


def cumplimiento(filas):
    """% de fases que cumplen cada objetivo y todos (solo los que se midieron en la fase)."""
    salida = {}
    for col, nombre in CUMPLE:
        medidas = [r[col] for r in filas if r.get(col)]
        salida[nombre] = (100 * sum(v == "sí" for v in medidas) / len(medidas)) if medidas else None
    todos = [all(r[c] == "sí" for c, _ in CUMPLE if r.get(c)) for r in filas]
    salida["todos"] = 100 * sum(todos) / len(todos) if todos else None
    return salida


def resumen_global(filas):
    """{(sala, estrategia): {fases, cumplimiento, respaldo, descargas}}."""
    grupos = {}
    for r in filas:
        grupos.setdefault((int(r["sala"]), r["estrategia"]), []).append(r)
    salida = {}
    for k, g in grupos.items():
        salida[k] = {"fases": len(g), **cumplimiento(g),
                     "respaldo": media_ic([numero(r.get("respaldo_goodput_mbps")) for r in g
                                           if numero(r.get("respaldo_goodput_mbps"))]),
                     "descargas": media_ic([numero(r.get("descargas_goodput_mbps")) for r in g
                                            if numero(r.get("descargas_goodput_mbps"))]),
                     "semillas": len({r["semilla"] for r in g})}
    return salida


def por_fase(filas):
    """Filas del CSV de detalle: por sala, escenario, fase y estrategia."""
    grupos = {}
    for r in filas:
        grupos.setdefault((int(r["sala"]), r["escenario"], r["fase"], r["estrategia"]), []).append(r)
    salida = []
    for (sala, esc, fase, estr), g in sorted(grupos.items()):
        fila = {"sala": sala, "escenario": esc, "fase": fase, "estrategia": estr, "n": len(g)}
        for col, _, _ in METRICAS:
            m, ic = media_ic([numero(r.get(col)) for r in g])
            fila[f"{col}_media"] = None if m is None else round(m, 2)
            fila[f"{col}_ic95"] = None if ic is None else round(ic, 2)
        for nombre, pct in cumplimiento(g).items():
            fila[f"cumple_{nombre}_pct"] = None if pct is None else round(pct, 1)
        salida.append(fila)
    return salida


def comparar(filas, a, b, columna):
    """Pares (sala, escenario, fase, semilla) con las dos estrategias: diferencia b - a."""
    valores = {}
    for r in filas:
        if r["estrategia"] in (a, b):
            valores.setdefault((r["sala"], r["escenario"], r["fase"], r["semilla"]), {})[r["estrategia"]] = \
                numero(r.get(columna))
    dif = [v[b] - v[a] for v in valores.values() if v.get(a) is not None and v.get(b) is not None]
    return {"pares": len(dif), "mediana": mediana(dif), **wilcoxon(dif)}


def fmt(v, d=1):
    return "-" if v is None else f"{v:.{d}f}"


def pct(v):
    return "-" if v is None else f"{v:.0f} %"


def cpu_por_sala(campana, ruta=CSV):
    """{sala: (promedio, máximo, fases)} de la CPU de la VM en TODAS las fases de la campaña
    (también las inválidas): muestra cuánto margen tuvo la VM."""
    por = {}
    with open(ruta, newline="") as f:
        for r in csv.DictReader(f):
            v = numero(r.get("cpu_pct"))
            if r.get("campana") == campana and v is not None:
                por.setdefault(int(r["sala"]), []).append(v)
    return {s: (sum(v) / len(v), max(v), len(v)) for s, v in por.items()}


def informe(campana, filas, fuera, pares, cpu=None):
    estrategias = orden_estrategias(filas)
    g = resumen_global(filas)
    lineas = [f"# Análisis de la campaña `{campana}`", "",
              f"{len(filas)} fases válidas; fuera del análisis: "
              + ", ".join(f"{v} {k}" for k, v in fuera.items()) + ".", ""]
    if cpu:
        lineas += ["CPU de la VM durante las fases (una fase con 90 % o más se marca inválida): "
                   + "; ".join(f"Sala {s}: promedio {p:.0f} %, máximo {m:.0f} % ({n} fases)"
                               for s, (p, m, n) in sorted(cpu.items())) + ".", ""]
    for sala in sorted({k[0] for k in g}):
        lineas += [f"## Sala {sala}", "",
                   "| Estrategia | Semillas | Fases | Voz | Video | Pagos | Web | Todo | Respaldo (Mbps) | Descargas (Mbps) |",
                   "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for e in estrategias:
            x = g.get((sala, e))
            if not x:
                continue
            ic = lambda t: f"{fmt(t[0])} ± {fmt(t[1])}" if t[0] is not None else "-"  # noqa: E731
            lineas.append(f"| {e} | {x['semillas']} | {x['fases']} | {pct(x['voz'])} | {pct(x['video'])} | "
                          f"{pct(x['pagos'])} | {pct(x['web'])} | **{pct(x['todos'])}** | "
                          f"{ic(x['respaldo'])} | {ic(x['descargas'])} |")
        lineas.append("")
    lineas += ["Porcentaje de fases que cumplen cada objetivo (solo donde se midió); 'Todo' = todos los medidos "
               "en la fase. Respaldo y descargas: goodput promedio ± intervalo del 95 % en las fases donde hubo.", ""]
    if pares:
        lineas += ["## Comparaciones en pares", "",
                   "Misma sala, escenario, fase y semilla con las dos estrategias. Diferencia = B − A; "
                   "p de Wilcoxon (dos colas, todas las fases juntas).", "",
                   "| A → B | Métrica | Pares | Mediana de la diferencia | p | Lectura |",
                   "| --- | --- | --- | --- | --- | --- |"]
        for (a, b, col, nombre, mejor), r in pares:
            if r["pares"] == 0:
                continue
            if r["p"] is None and r["pares"] >= MIN_PARES:
                lectura = "iguales (casi todos los pares sin diferencia)"
            elif r["p"] is None:
                lectura = "pocos pares"
            elif r["p"] >= 0.05:
                lectura = "sin diferencia significativa"
            else:
                gana_b = (r["mediana"] < 0) if mejor == "menor" else (r["mediana"] > 0)
                lectura = f"**{b if gana_b else a} es mejor**"
            p = "-" if r["p"] is None else ("< 0.001" if r["p"] < 0.001 else f"{r['p']:.3f}")
            lineas.append(f"| {a} → {b} | {nombre} | {r['pares']} | {fmt(r['mediana'], 2)} | {p} | {lectura} |")
        lineas.append("")
    return "\n".join(lineas)


def main():
    p = argparse.ArgumentParser(description="Análisis de una campaña de comparación (PCIII-23)")
    p.add_argument("--campana", required=True)
    p.add_argument("--csv", default=CSV)
    p.add_argument("--comparar", default=COMPARAR, help="pares A:B separados por coma")
    args = p.parse_args()
    if not os.path.exists(args.csv):
        sys.exit(f"No existe {args.csv}: primero corre la campaña (experimentos/campana.py)")
    filas, fuera = cargar(args.campana, args.csv)
    if not filas:
        sys.exit(f"No hay fases válidas de la campaña '{args.campana}' en {args.csv}")
    pares = []
    for par in args.comparar.split(","):
        a, _, b = par.partition(":")
        for col, nombre, mejor in METRICAS:
            pares.append(((a, b, col, nombre, mejor), comparar(filas, a, b, col)))
    detalle = por_fase(filas)
    ruta_csv = os.path.join(RESULTADOS, f"analisis_{args.campana}.csv")
    for ruta in (ruta_csv, os.path.join(RESULTADOS, f"analisis_{args.campana}.md")):
        if os.path.exists(ruta) and not os.access(ruta, os.W_OK):
            sys.exit(f"No se puede escribir {ruta} (quedó de root por una corrida con sudo). Una vez:\n"
                     f"  sudo chown -R $USER:$USER {RAIZ}")
    with open(ruta_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(detalle[0].keys()))
        w.writeheader()
        w.writerows(detalle)
    texto = informe(args.campana, filas, fuera, pares, cpu_por_sala(args.campana, args.csv))
    ruta_md = os.path.join(RESULTADOS, f"analisis_{args.campana}.md")
    with open(ruta_md, "w") as f:
        f.write(texto + "\n")
    print(texto)
    print(f"\n*** Detalle por fase: {ruta_csv}\n*** Resumen: {ruta_md}")


if __name__ == "__main__":
    main()
