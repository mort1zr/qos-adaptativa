#!/usr/bin/env python3
"""
Campaña de comparación entre estrategias (PCIII-23; punto 1: repeticiones).

Corre todos los escenarios con varias semillas, salas y estrategias, y guarda
una fila por fase en experimentos/resultados/comparacion.csv (con el nombre de
la campaña). Cada semilla con ruido es una situación distinta: cambia qué
equipos generan tráfico y cuánto (±10 %), no solo el orden.

  sudo python3 experimentos/campana.py --nombre pciii23 --salas 1,4 --semillas 1-5 --estrategias prioridad,estatica
  sudo python3 experimentos/campana.py --nombre pciii23 --salas 1,4 --semillas 1-3 --estrategias sin_qos,fila_corta
  python3 experimentos/campana.py --nombre pciii23 --estado
  python3 experimentos/analisis.py --campana pciii23            # el análisis, aparte

Orden: semilla -> sala -> estrategia -> escenarios. Así, si se corta a mitad,
lo que hay está balanceado (todas las estrategias de las primeras semillas).
Cada bloque (semilla, sala, estrategia) levanta la red de cero: corridas
independientes. Se puede interrumpir (Ctrl+C, VM apagada) y volver a lanzar con
el mismo comando: lo que ya se guardó no se repite.

Necesita Ryu con controlador/qos_app.py durante TODA la campaña. Antes de dejarla
corriendo de noche: la VM sin suspensión ni bloqueo de pantalla.
"""
import argparse
import csv
import datetime
import os
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)
for ruta in (os.path.join(RAIZ, "topologia"), AQUI):
    if ruta not in sys.path:
        sys.path.append(ruta)

from escenarios.escenario import (CONTEXTO, ESTRATEGIAS, cargar_escenarios, devolver_al_usuario,  # noqa: E402
                                  ejecutar, guardar_csv)
from trafico.generador import cargar_perfiles  # noqa: E402

CSV = os.path.join(AQUI, "resultados", "comparacion.csv")
REGISTRO = os.path.join(AQUI, "resultados", "campanas.log")
SEGUNDOS_EXTRA_FASE = 15        # sondas, espera de procesos y del último sondeo de telemetría
SEGUNDOS_EXTRA_BLOQUE = 270     # levantar y bajar la red de 282 equipos (medido en la VM: ~4.5 min)


def rango(texto: str) -> list:
    """'1-5' -> [1, 2, 3, 4, 5]; '1,3,5' -> [1, 3, 5]."""
    valores = []
    for parte in texto.split(","):
        a, _, b = parte.strip().partition("-")
        valores += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return valores


def hechos(campana: str, ruta: str = CSV) -> dict:
    """{(sala, semilla, estrategia, escenario): fases guardadas} de la campaña."""
    cuenta = {}
    if not os.path.exists(ruta):
        return cuenta
    with open(ruta, newline="") as f:
        for fila in csv.DictReader(f):
            if fila.get("campana") != campana:
                continue
            k = (int(fila["sala"]), int(fila["semilla"]), fila["estrategia"], fila["escenario"])
            cuenta[k] = cuenta.get(k, 0) + 1
    return cuenta


def bloques(campana, salas, semillas, estrategias, datos, ruta: str = CSV) -> list:
    """[(semilla, sala, estrategia, [escenarios pendientes])], en el orden de ejecución."""
    listos = hechos(campana, ruta)
    fases = {n: len(e["fases"]) for n, e in datos["escenarios"].items()}
    salida = []
    for semilla in semillas:
        for sala in salas:
            for estrategia in estrategias:
                pend = [n for n in datos["escenarios"]
                        if listos.get((sala, semilla, estrategia, n), 0) < fases[n]]
                salida.append((semilla, sala, estrategia, pend))
    return salida


def segundos_de(datos, nombres) -> float:
    return sum(f["duracion_s"] + SEGUNDOS_EXTRA_FASE for n in nombres for f in datos["escenarios"][n]["fases"])


def duracion(segundos: float) -> str:
    h, m = divmod(int(segundos // 60), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def estado(campana, salas, semillas, estrategias, datos):
    todos = bloques(campana, salas, semillas, estrategias, datos)
    total_esc = len(todos) * len(datos["escenarios"])
    pend_esc = sum(len(p) for *_, p in todos)
    falta = sum(segundos_de(datos, p) + (SEGUNDOS_EXTRA_BLOQUE if p else 0) for *_, p in todos)
    print(f"Campaña '{campana}': {total_esc - pend_esc} de {total_esc} escenarios listos; "
          f"faltan unos {duracion(falta)} de VM.")
    print(f"  {'Semilla':>7s} {'Sala':>4s} {'Estrategia':12s} Listos")
    for semilla, sala, estrategia, pend in todos:
        n = len(datos["escenarios"])
        print(f"  {semilla:>7} {sala:>4} {estrategia:12s} {n - len(pend):>2}/{n}"
              + (f"   faltan: {', '.join(pend)}" if 0 < len(pend) < n else ""))


def registrar(texto: str):
    os.makedirs(os.path.dirname(REGISTRO), exist_ok=True)
    with open(REGISTRO, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {texto}\n")
    devolver_al_usuario(REGISTRO)
    print(f"*** {texto}")


def main():
    p = argparse.ArgumentParser(description="Campaña de comparación entre estrategias (PCIII-23)")
    p.add_argument("--nombre", required=True, help="nombre de la campaña (p. ej. pciii23)")
    p.add_argument("--salas", default="1,4")
    p.add_argument("--semillas", default="1-5", help="'1-5' o '1,2,3'")
    p.add_argument("--estrategias", default="prioridad,estatica")
    p.add_argument("--ruido", type=float, default=0.1, help="variación de las intensidades (0.1 = ±10 %%)")
    p.add_argument("--estado", action="store_true", help="muestra el avance y el tiempo que falta")
    p.add_argument("--escenarios", help="solo estos (separados por coma); por defecto, todos")
    p.add_argument("--escala", type=float, default=1.0, help="acorta las fases: SOLO para probar el script")
    p.add_argument("--datapath", choices=("kernel", "user"), default="kernel")
    args = p.parse_args()
    salas, semillas = rango(args.salas), rango(args.semillas)
    estrategias = [e.strip() for e in args.estrategias.split(",")]
    for e in estrategias:
        if e not in ESTRATEGIAS:
            sys.exit(f"Estrategia desconocida: {e} (hay: {', '.join(ESTRATEGIAS)})")
    perfiles = cargar_perfiles()
    datos = cargar_escenarios(perfiles=perfiles)
    if args.escenarios:
        pedidos = [n.strip() for n in args.escenarios.split(",")]
        faltan = [n for n in pedidos if n not in datos["escenarios"]]
        if faltan:
            sys.exit(f"Escenarios desconocidos: {', '.join(faltan)}")
        datos = dict(datos, escenarios={n: datos["escenarios"][n] for n in pedidos})

    if args.estado:
        estado(args.nombre, salas, semillas, estrategias, datos)
        return
    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo (levanta la red de Mininet)")

    pendientes = [b for b in bloques(args.nombre, salas, semillas, estrategias, datos) if b[3]]
    if not pendientes:
        print(f"La campaña '{args.nombre}' ya está completa para esas salas, semillas y estrategias.")
        return
    falta = sum(segundos_de(datos, b[3]) + SEGUNDOS_EXTRA_BLOQUE for b in pendientes)
    registrar(f"campaña '{args.nombre}': {len(pendientes)} bloques pendientes "
              f"(salas {salas}, semillas {semillas}, {', '.join(estrategias)}, ruido {args.ruido}); "
              f"unos {duracion(falta)}")
    inicio = time.time()

    def guardar(filas, contexto):
        guardar_csv(CSV, filas)
        guardar_csv(CONTEXTO, contexto)

    for i, (semilla, sala, estrategia, pend) in enumerate(pendientes, 1):
        registrar(f"bloque {i}/{len(pendientes)}: semilla {semilla}, Sala {sala}, {estrategia} "
                  f"({len(pend)} escenarios)")
        try:
            ejecutar(datos, perfiles, pend, [estrategia], sala, semilla, args.ruido, args.escala, args.datapath,
                     al_terminar=guardar, extra={"campana": args.nombre})
        except KeyboardInterrupt:
            registrar("interrumpida a mano: vuelve a lanzar el mismo comando para seguir")
            sys.exit(1)
        except Exception as e:                       # p. ej. Ryu se cayó: parar, se retoma después
            registrar(f"se detuvo en el bloque {i}: {e}")
            sys.exit("La campaña se puede retomar con el mismo comando cuando el problema esté resuelto.")
        hecho = time.time() - inicio
        resto = sum(segundos_de(datos, b[3]) + SEGUNDOS_EXTRA_BLOQUE for b in pendientes[i:])
        registrar(f"bloque {i} listo; van {duracion(hecho)}, faltan unos {duracion(resto)}")
    registrar(f"campaña '{args.nombre}' completa ({duracion(time.time() - inicio)})")
    print(f"*** Resultados en {CSV}\n*** Análisis: python3 experimentos/analisis.py --campana {args.nombre}")


if __name__ == "__main__":
    main()
