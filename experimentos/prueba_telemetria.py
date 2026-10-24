#!/usr/bin/env python3
"""
Prueba de la telemetría por flujo, área y clase (historia PCIII-16).

Genera tráfico UDP de tasa conocida desde varias áreas a la vez y compara lo que
guardó el controlador (datos/telemetria.db) con lo que se envió:

  Contabilidad     ofcon1  <- Internet (descargas)        2.0 Mbps  bajada  masivo
  Sistemas         ofsis1  -> Internet (IA generativa)    0.5 Mbps  subida  negocio
  Telefonía Sala 1 sa1tel  -> central de la oficina       VoIP      subida  tiempo_real
  WiFi clientes S1 sa1cli1 <- Internet (streaming)        3.0 Mbps  bajada  restringido

Criterio: el promedio medido por área y clase difiere menos de 10 % de lo
enviado (contando las cabeceras Ethernet/IP/UDP, que el switch también cuenta).
Al final muestra la consulta de ejemplo: demanda de Contabilidad.

Requiere Ryu con la aplicación del proyecto (en otra terminal, con el .venv):
  ryu-manager controlador/qos_app.py
Uso:
  sudo python3 experimentos/prueba_telemetria.py
Resultados: experimentos/resultados/prueba_telemetria.csv
"""
import argparse
import csv
import datetime
import os
import sqlite3
import sys
import time

import yaml
from mininet.log import info, setLogLevel

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "topologia"))
sys.path.insert(0, AQUI)

from empresa_xyz import AVISO_RYU, CONFIG_DEFECTO, EmpresaXYZ, controlador_activo  # noqa: E402
from controlador.telemetria import demanda, leer_config, uso_enlaces  # noqa: E402
import medicion as m  # noqa: E402

CSV = os.path.join(AQUI, "resultados", "prueba_telemetria.csv")
CABECERAS = 42          # Ethernet 14 + IP 20 + UDP 8: el switch cuenta el paquete completo
# (área, origen, destino, puerto, pps, bytes de datos, sentido esperado, clase esperada, sede)
FLUJOS = [
    ("Contabilidad",  "inetupd", "ofcon1",  5801, 208, 1200, "bajada", "masivo",      0),
    ("Sistemas",      "ofsis1",  "inetia",  5802, 52,  1200, "subida", "negocio",     0),
    ("Telefonía",     "sa1tel",  "ofpbx",   5803, 50,  160,  "subida", "tiempo_real", 1),
    ("WiFi clientes", "inetstr", "sa1cli1", 5804, 312, 1200, "bajada", "restringido", 1),
]
TOLERANCIA_PCT = 10
AVISO_TELEMETRIA = (
    "Ryu no está guardando telemetría en {db}.\n"
    "  La red funciona con cualquier controlador, pero la telemetría solo la guarda\n"
    "  la aplicación del proyecto. En la Terminal 1 (con el .venv activo):\n"
    "       cd ~/qos-adaptativa\n"
    "       ryu-manager controlador/qos_app.py\n"
    "  Debe mostrar 'QoSApp: telemetría cada 5 s ...' y luego\n"
    "  'Switch de acceso acc0 (sede 0) conectado' (y acc1..acc4).\n"
    "  Si muestra errores, cópialos.")


def ultimo_sondeo(db):
    """Hora del último sondeo que guardó Ryu, o None."""
    if not os.path.exists(db):
        return None
    try:
        con = sqlite3.connect(db)
        ts = con.execute("SELECT MAX(ts) FROM sondeos").fetchone()[0]
        con.close()
        return ts
    except sqlite3.Error:
        return None


def esperar_telemetria(db, desde, limite_s):
    """Espera a que aparezca un sondeo posterior a 'desde'. True si llegó."""
    fin = time.time() + limite_s
    while time.time() < fin:
        ts = ultimo_sondeo(db)
        if ts and ts > desde:
            return True
        time.sleep(1)
    return False


def main():
    p = argparse.ArgumentParser(description="Prueba de la telemetría por área y clase")
    p.add_argument("--duracion", type=int, default=60, help="segundos de tráfico")
    p.add_argument("--datapath", choices=("kernel", "user"), default="kernel")
    args = p.parse_args()
    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo")
    if not controlador_activo():
        sys.exit(AVISO_RYU.format(ip="127.0.0.1", puerto=6633))

    cfg_tel = leer_config()
    db = cfg_tel["base_datos"]
    setLogLevel("info")
    with open(CONFIG_DEFECTO) as f:
        cfg = yaml.safe_load(f)
    emp = EmpresaXYZ(cfg, datapath=args.datapath)
    emp.construir()
    emp.net.start()
    filas = []
    try:
        emp.configurar(estrategia="colas")
        arranque = time.time()
        info("*** Esperando 8 s a que los switches se conecten a Ryu\n")
        time.sleep(8)
        info("*** Comprobando que Ryu (controlador/qos_app.py) guarda telemetría...\n")
        if not esperar_telemetria(db, arranque, cfg_tel["intervalo_s"] * 4):
            info("\n" + AVISO_TELEMETRIA.format(db=db) + "\n")
            return
        info("    sí: la telemetría está activa\n")
        net = emp.net
        for _, o, d, *_ in FLUJOS:
            net.get(o).cmd(f"ping -c2 -W2 {net.get(d).IP()}")
        limite = args.duracion + 30
        receptores, emisores = [], []
        for _, o, d, puerto, pps, largo, *_ in FLUJOS:
            receptores.append(m.receptor_udp(net.get(d), puerto, limite)[0])
        time.sleep(1)
        inicio = time.time()
        for _, o, d, puerto, pps, largo, *_ in FLUJOS:
            emisores.append(m.emisor_udp(net.get(o), net.get(d).IP(), puerto,
                                         {"pps": pps, "largo": largo}, args.duracion))
        info(f"*** Tráfico de {len(FLUJOS)} áreas durante {args.duracion} s "
             f"(telemetría cada {cfg_tel['intervalo_s']} s)\n")
        for pr in emisores:
            m.esperar(pr, limite=args.duracion + 20)
        fin = time.time()
        for pr in receptores:
            m.esperar(pr, limite=15)
        time.sleep(cfg_tel["intervalo_s"] * 2)      # que entre el último sondeo

        # Se evalúa el tramo central, lejos del arranque y del final del tráfico.
        margen = cfg_tel["intervalo_s"] * 2
        ventana_min = (fin - inicio - 2 * margen) / 60
        for area, o, d, puerto, pps, largo, sentido, clase, sede in FLUJOS:
            esperado = pps * (largo + CABECERAS) * 8 / 1e6
            medidas = [x for x in demanda(db, ventana_min, area=area, sede_id=sede, ahora=fin - margen)
                       if x["sentido"] == sentido]
            medido = sum(x["promedio_mbps"] for x in medidas if x["clase"] == clase)
            clases = sorted({x["clase"] for x in medidas})
            error = 100 * abs(medido - esperado) / esperado
            cumple = "sí" if error < TOLERANCIA_PCT and clases == [clase] else "no"
            filas.append({"fecha": datetime.datetime.now().isoformat(timespec="seconds"),
                          "area": area, "sede_id": sede, "origen": o, "destino": d, "sentido": sentido,
                          "clase_esperada": clase, "clases_medidas": "+".join(clases),
                          "esperado_mbps": round(esperado, 3), "medido_mbps": round(medido, 3),
                          "error_pct": round(error, 1), "cumple": cumple})
        enlaces = uso_enlaces(db, ventana_min, ahora=fin - margen)
    finally:
        emp.limpiar()
        emp.net.stop()

    if filas:
        os.makedirs(os.path.dirname(CSV), exist_ok=True)
        nuevo = not os.path.exists(CSV)
        with open(CSV, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
            if nuevo:
                w.writeheader()
            w.writerows(filas)
        info(f"\n    {'Área':14s} {'Sentido':7s} {'Clase esperada':15s} {'Clase medida':15s} "
             f"{'Enviado':>9s} {'Medido':>9s} {'Error':>7s}  Cumple\n")
        for f in filas:
            info(f"    {f['area']:14s} {f['sentido']:7s} {f['clase_esperada']:15s} {f['clases_medidas']:15s} "
                 f"{f['esperado_mbps']:6.3f} Mb {f['medido_mbps']:6.3f} Mb {f['error_pct']:5.1f} %  {f['cumple']}\n")
        info("\n    Uso de los enlaces en el mismo periodo:\n")
        for e in enlaces:
            info(f"      sede {e['sede_id']} {e['sentido']:6s} {e['promedio_mbps']:6.2f} Mbps "
                 f"de {e['capacidad_mbps']:.0f}\n")
        info(f"\n*** Resultados agregados a {CSV}\n")
        info("*** Consulta de ejemplo (sin sudo): "
             "python3 controlador/consultas.py demanda --area Contabilidad --minutos 10\n")


if __name__ == "__main__":
    main()
