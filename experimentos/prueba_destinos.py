#!/usr/bin/env python3
"""
Clasificación por destino con reglas por adelantado (historia PCIII-20).

Con Ryu corriendo controlador/qos_app.py y el clasificador 'destino'
(politicas/destinos.yaml), en la Sala elegida:

  1. Cada servicio se reconoce por su destino. Un ping corto por par
     origen -> destino (videollamada, troncal SIP, IA generativa desde Sistemas
     y desde Contabilidad, YouTube desde la PC de música y desde el WiFi de
     clientes, pagos, descargas, la central telefónica, el servidor de gestión
     y la navegación web, que NO está en la tabla). Se compara la clase que
     decidió el controlador con la esperada y con la "etiqueta verdadera" del
     clasificador 'politica' (que lo sabe todo).
  2. Por adelantado frente a reactivo. Se borran las reglas por flujo y se
     hacen pings a un destino de la tabla (Teams) y a uno fuera de ella (web):
     cuánto más tarda el primer paquete que los demás. Con la regla instalada
     por adelantado el primer paquete no espera al controlador.
  3. La telemetría no se pierde: el flujo hacia Teams tiene igual su regla por
     flujo (creada con la copia del primer paquete) y su decisión registrada.

Uso (Ryu con controlador/qos_app.py en otra terminal):
  sudo python3 experimentos/prueba_destinos.py            # Sala 1, ~2 min
Resultados: experimentos/resultados/prueba_destinos.csv
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
sys.path.insert(0, RAIZ)
for ruta in (os.path.join(RAIZ, "topologia"), AQUI):
    if ruta not in sys.path:
        sys.path.append(ruta)

import yaml  # noqa: E402

from controlador import api  # noqa: E402
from controlador.clasificadores import PorPolitica, armar_flujo  # noqa: E402
from controlador.inventario import Inventario  # noqa: E402
from controlador.telemetria import leer_config, percentil  # noqa: E402
from politicas.cargador import cargar  # noqa: E402

CSV = os.path.join(AQUI, "resultados", "prueba_destinos.csv")
CAMPOS = ["fecha", "sala", "prueba", "origen", "destino", "esperado", "decidido", "servicio",
          "politica", "via", "motivo", "valor", "criterio", "cumple"]
RONDAS = 5


def pares(sala):
    s = f"sa{sala}"
    # (origen, destino, clase esperada, servicio esperado)
    return [(f"{s}caja", "inetvc", "tiempo_real", "videoconferencia"),
            ("ofpbx", "inetsip", "tiempo_real", "troncal_sip"),
            ("ofsis1", "inetia", "negocio", "ia_generativa"),
            ("ofcon1", "inetia", "masivo", "ia_generativa"),
            (f"{s}musica", "inetstr", "negocio", "streaming"),
            (f"{s}cli1", "inetstr", "restringido", "streaming"),
            (f"{s}pos1", "inetpago1", "critico", "pagos"),
            (f"{s}caja", "inetupd", "masivo", "descargas"),
            (f"{s}tel", "ofpbx", "tiempo_real", "voip"),
            (f"{s}srv", "ofcms", "critico", "gestion"),
            (f"{s}caja", "inetweb", "masivo", "desconocido"),
            (f"{s}cli1", "inetweb", "restringido", "desconocido")]


def si(c):
    return "sí" if c else "no"


def rtts(host, ip, n=10):
    salida = host.cmd(f"ping -c {n} -i 0.2 -W 2 {ip}")
    return [float(x) for x in re.findall(r"time=([\d.]+)", salida)]


def prueba_reconocimiento(net, sala, db, intervalo):
    from mininet.log import info
    info("\n*** Prueba 1 · cada servicio se reconoce por su destino\n")
    api.poner_clasificador("destino")
    time.sleep(1)
    t0 = time.time()
    for o, d, _, _ in pares(sala):
        net.get(o).cmd(f"ping -c 3 -i 0.2 -W 2 {net.get(d).IP()}")
    time.sleep(intervalo + 2)
    inv, pol = Inventario(), cargar()
    oraculo = PorPolitica(pol)
    con = sqlite3.connect(db)
    filas = []
    info(f"    {'Origen':10s} {'Destino':10s} {'Esperado':12s} {'Decidido':12s} {'Servicio':17s} "
         f"{'Política':12s} {'Vía':10s} Cumple\n")
    for o, d, clase, servicio in pares(sala):
        ho, hd = net.get(o), net.get(d)
        r = con.execute("SELECT clase, servicio, via, motivo FROM decisiones WHERE ts >= ? AND proto = 1 AND "
                        "origen_ip = ? AND destino_ip = ? AND sentido = 'subida' AND clasificador = 'destino' "
                        "ORDER BY ts LIMIT 1", (t0 - 1, ho.IP(), hd.IP())).fetchone()
        decidido, serv, via, motivo = r if r else ("(sin decisión)", "", "", "")
        local = inv.equipo(ho.IP())
        sw = next(s for s in inv.accesos() if s["sede_id"] == local["sede_id"])
        verdad = oraculo.clasificar(armar_flujo(inv, sw, ho.IP(), hd.IP(), 1, sw["puerto_sede"])).clase
        ok = decidido == clase and serv == servicio and decidido == verdad
        info(f"    {o:10s} {d:10s} {clase:12s} {decidido:12s} {serv:17s} {verdad:12s} {via:10s} {si(ok)}\n")
        filas.append({"prueba": "reconocimiento", "origen": o, "destino": d, "esperado": clase,
                      "decidido": decidido, "servicio": serv, "politica": verdad, "via": via, "motivo": motivo,
                      "criterio": f"clase {clase}, servicio {servicio}, igual a la política", "cumple": si(ok)})
    con.close()
    return filas


def prueba_adelantado(net, sala, db, intervalo):
    from mininet.log import info
    info(f"\n*** Prueba 2 · primer paquete: destino en la tabla (Teams) frente a fuera de ella (web), "
         f"{RONDAS} rondas\n")
    caja = net.get(f"sa{sala}caja")
    destinos = {"en la tabla (Teams)": net.get("inetvc").IP(), "fuera de la tabla (web)": net.get("inetweb").IP()}
    extra = {k: [] for k in destinos}
    for i in range(RONDAS):
        api.poner_clasificador("destino")           # borra las reglas por flujo y reinstala las de adelantado
        time.sleep(1.5)
        for k, ip in destinos.items():
            r = rtts(caja, ip)
            if len(r) >= 5:
                extra[k].append(r[0] - percentil(r[1:], 50))
    prom = {k: (sum(v) / len(v) if v else None) for k, v in extra.items()}
    for k, v in prom.items():
        info(f"    {k:26s} el primer ping tarda {v:+.1f} ms respecto de la mediana del resto\n"
             if v is not None else f"    {k:26s} sin respuestas\n")
    conocido, desconocido = prom["en la tabla (Teams)"], prom["fuera de la tabla (web)"]
    ok = conocido is not None and desconocido is not None and conocido < 3 and conocido < desconocido
    filas = [{"prueba": "por_adelantado", "destino": k, "valor": None if v is None else round(v, 2),
              "criterio": "primer paquete sin espera extra (< 3 ms) y menor que el reactivo",
              "cumple": si(ok) if k.startswith("en") else "-"} for k, v in prom.items()]

    info("\n*** Prueba 3 · la telemetría sigue viendo el flujo que fue por adelantado\n")
    time.sleep(intervalo + 2)
    reglas = subprocess.run(["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", f"acc{sala}", "cookie=0x16/-1"],
                            capture_output=True, text=True).stdout
    por_flujo = sum(1 for linea in reglas.splitlines() if "nw_dst=" + destinos["en la tabla (Teams)"] in linea
                    or "nw_src=" + destinos["en la tabla (Teams)"] in linea)
    con = sqlite3.connect(db)
    vias = dict(con.execute("SELECT via, COUNT(*) FROM decisiones WHERE ts >= ? AND clasificador = 'destino' "
                            "AND (destino_ip = ? OR origen_ip = ?) GROUP BY via",
                            (time.time() - 300, destinos["en la tabla (Teams)"],
                             destinos["en la tabla (Teams)"])).fetchall())
    con.close()
    estado = api.estado()
    ok = por_flujo == 2 and vias.get("proactiva", 0) > 0
    info(f"    reglas por flujo hacia/desde Teams en acc{sala}: {por_flujo} (una por sentido); "
         f"decisiones por adelantado: {vias.get('proactiva', 0)}, reactivas: {vias.get('reactiva', 0)}\n"
         f"    reglas por adelantado instaladas: {estado.get('reglas_por_adelantado')}\n")
    filas.append({"prueba": "telemetria", "destino": "Teams", "valor": f"{por_flujo} reglas por flujo, "
                  f"{vias.get('proactiva', 0)} decisiones por adelantado",
                  "criterio": "2 reglas por flujo (ida y vuelta) y decisiones 'proactiva'", "cumple": si(ok)})
    filas.append({"prueba": "reglas_por_adelantado", "valor": str(estado.get("reglas_por_adelantado")),
                  "criterio": "-", "cumple": "-"})
    return filas


def main():
    p = argparse.ArgumentParser(description="Clasificación por destino (PCIII-20)")
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
    db, intervalo = cfg_ctl["base_datos"], cfg_ctl["intervalo_s"]
    setLogLevel("info")
    with open(CONFIG_DEFECTO) as f:
        cfg = yaml.safe_load(f)
    emp = EmpresaXYZ(cfg, datapath=args.datapath)
    emp.construir()
    emp.net.start()
    filas = []
    fecha = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        emp.configurar(estrategia="colas")
        info("*** Esperando 8 s a que los switches se conecten a Ryu\n")
        time.sleep(8)
        api.poner_clasificador("ninguno")
        for o, d, _, _ in pares(args.sala):          # aprender MAC y ARP antes de medir
            emp.net.get(o).cmd(f"ping -c 2 -W 2 {emp.net.get(d).IP()}")
        filas += prueba_reconocimiento(emp.net, args.sala, db, intervalo)
        filas += prueba_adelantado(emp.net, args.sala, db, intervalo)
    finally:
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
    info("\n    Resumen PCIII-20\n")
    rec = [f for f in filas if f["prueba"] == "reconocimiento"]
    info(f"    {si(all(f['cumple'] == 'sí' for f in rec))}  reconocimiento: "
         f"{sum(f['cumple'] == 'sí' for f in rec)}/{len(rec)} pares con la clase y el servicio esperados\n")
    for f in filas:
        if f["prueba"] in ("por_adelantado", "telemetria") and f["cumple"] != "-":
            info(f"    {f['cumple']:3s} {f['prueba']}: {f['valor']} ({f['criterio']})\n")
    info(f"\n*** Resultados agregados a {CSV}\n")


if __name__ == "__main__":
    main()
