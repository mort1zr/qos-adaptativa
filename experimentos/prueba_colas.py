#!/usr/bin/env python3
"""
Validación de aislamiento y préstamo de las colas HTB (historia PCIII-15).

Antes de que el controlador clasifique solo (Sprint 3), aquí se clasifica a
mano: reglas OpenFlow en los switches de acceso mandan el tráfico de prueba a
su cola según el puerto de destino (set_queue). En una red real la voz se
reconocería por su marca DSCP (EF) o por una ACL; para una prueba alcanza con
el puerto. Tres pruebas, en la Sala elegida:

  1. Aislamiento, con el enlace saturado por descargas (3 clientes WiFi bajando
     de Internet + respaldo del servidor de sala subiendo a la oficina).
     Llamada VoIP y videollamada medidas en tres variantes:
       sin_qos           una cola, FIFO larga (red sin gestionar)
       colas_sin_reglas  6 colas, pero todo cae en "masivo"
       colas_con_reglas  voz y video en "tiempo_real"
     Criterio: con reglas, jitter < 30 ms y el resto de objetivos de calidad.

  2. Garantía: un flujo UDP en "critico" al 90 % de su garantía mientras las
     descargas saturan el enlace. Criterio: recibe su tasa con pérdida < 1 %.

  3. Préstamo y techo, con el enlace libre: una descarga TCP sola en "masivo",
     en "tiempo_real" y en "restringido". Criterio: usa más que su garantía
     (préstamo HTB) y no pasa de su techo.

Uso (Ryu corriendo en otra terminal):
  sudo python3 experimentos/prueba_colas.py            # Sala 1, ~5 min
Resultados: experimentos/resultados/prueba_colas.csv
"""
import argparse
import csv
import datetime
import os
import subprocess
import sys
import time

import yaml
from mininet.log import info, setLogLevel

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "topologia"))
sys.path.insert(0, AQUI)

from empresa_xyz import AVISO_RYU, CONFIG_DEFECTO, EmpresaXYZ, controlador_activo  # noqa: E402
import medicion as m  # noqa: E402
import prueba_congestion as pc  # noqa: E402

CSV = os.path.join(AQUI, "resultados", "prueba_colas.csv")
CAMPOS = ["fecha", "sala", "prueba", "variante", "flujo", "clase", "cola", "garantia_mbps",
          "techo_mbps", "mbps", "latencia_ms", "latencia_p95_ms", "jitter_ms", "perdida_pct",
          "mos", "criterio", "cumple"]
COOKIE = "0x15"                       # marca las reglas de esta prueba para borrarlas juntas
PUERTO_GARANTIA = 5601
PUERTOS_PRESTAMO = {"masivo": 5701, "tiempo_real": 5702, "restringido": 5705}


# ---------------- reglas OpenFlow manuales ----------------
def ofctl(*args):
    r = subprocess.run(["ovs-ofctl", "-O", "OpenFlow13"] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ovs-ofctl {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def ofport(interfaz):
    r = subprocess.run(["ovs-vsctl", "get", "Interface", interfaz, "ofport"],
                       capture_output=True, text=True, check=True)
    return int(r.stdout.strip())


class Reglas:
    """Reglas set_queue en los switches de acceso (acc0 de la oficina y el de la sala)."""

    def __init__(self, emp, sala):
        self.switches = {}
        for sw, puerto, _, sentido in emp.puertos_acceso:
            if sw in ("acc0", f"acc{sala}"):
                self.switches.setdefault(sw, {})[sentido] = ofport(puerto)

    def poner(self, proto, puerto_destino, cola):
        """Manda a 'cola' el tráfico proto/puerto_destino, en ambos sentidos del enlace."""
        for sw, p in self.switches.items():
            # subida: entra por el lado de la sede (bajada) y sale hacia el operador (subida)
            for entra, sale in ((p["bajada"], p["subida"]), (p["subida"], p["bajada"])):
                ofctl("add-flow", sw,
                      f"cookie={COOKIE},priority=100,in_port={entra},{proto},tp_dst={puerto_destino},"
                      f"actions=set_queue:{cola},output:{sale}")

    def borrar(self):
        for sw in self.switches:
            ofctl("del-flows", sw, f"cookie={COOKIE}/-1")

    def contar(self):
        return sum(ofctl("dump-flows", sw).count(f"cookie={COOKIE}") for sw in self.switches)


# ---------------- pruebas ----------------
def poner_estrategia(emp, estrategia):
    emp.colas.hoja = "fifo" if estrategia == "sin_qos" else "pfifo:64"
    for _, puerto, mbps, _ in emp.puertos_acceso:
        if estrategia == "sin_qos":
            emp.colas.linea_base(puerto, mbps)
        else:
            emp.colas.aplicar(puerto, mbps)


def prueba_aislamiento(emp, reglas, sala, duracion, tasas):
    pol, filas = emp.colas.pol, []
    tr = pol.cola("tiempo_real")
    for variante in ("sin_qos", "colas_sin_reglas", "colas_con_reglas"):
        info(f"\n*** Prueba 1 · aislamiento · {variante}\n")
        poner_estrategia(emp, "sin_qos" if variante == "sin_qos" else "colas")
        reglas.borrar()
        if variante == "colas_con_reglas":
            reglas.poner("udp", pc.PUERTO_VOZ, tr)
            reglas.poner("udp", pc.PUERTO_VIDEO, tr)
            info(f"    {reglas.contar()} reglas: voz (udp/{pc.PUERTO_VOZ}) y video "
                 f"(udp/{pc.PUERTO_VIDEO}) -> cola {tr} (tiempo_real)\n")
        time.sleep(1)
        for f in pc.fase(emp.net, sala, variante, True, duracion):
            es_sonda = f["clase"] in ("voip", "videoconferencia")
            clase = ("tiempo_real" if variante == "colas_con_reglas" and es_sonda
                     else "única" if variante == "sin_qos" else "masivo")
            g, t = tasas.get(clase, (None, None))
            filas.append({
                "prueba": "aislamiento", "variante": variante, "flujo": f["clase"],
                "clase": clase, "cola": pol.cola(clase) if clase in pol.por_nombre else 0,
                "garantia_mbps": g, "techo_mbps": t, "mbps": f.get("mbps"),
                "latencia_ms": f.get("latencia_ms"), "latencia_p95_ms": f.get("latencia_p95_ms"),
                "jitter_ms": f.get("jitter_ms"), "perdida_pct": f.get("perdida_pct"),
                "mos": f.get("mos"),
                "criterio": "objetivos de calidad (jitter < 30 ms, pérdida, p95, MOS)" if es_sonda else "-",
                "cumple": f.get("cumple", "-") if es_sonda else "-"})
    reglas.borrar()
    return filas


def prueba_garantia(emp, reglas, sala, duracion, tasas):
    info("\n*** Prueba 2 · garantía de 'critico' con el enlace saturado\n")
    net, s = emp.net, f"sa{sala}"
    poner_estrategia(emp, "colas")
    reglas.borrar()
    reglas.poner("udp", PUERTO_GARANTIA, emp.colas.pol.cola("critico"))
    garantia, techo = tasas["critico"]
    objetivo = 0.9 * garantia
    largo = 1200
    perfil = {"pps": round(objetivo * 1e6 / ((largo + 42) * 8)), "largo": largo}  # 42 B de cabeceras
    srv, pbx = net.get(f"{s}srv"), net.get("ofpbx")   # servidor de sala -> oficina (subida)
    upd, clientes = net.get("inetupd"), [net.get(f"{s}cli{i}") for i in (1, 2, 3)]
    bak = net.get("ofbak")
    limite = duracion + 40
    rx, ruta = m.receptor_udp(pbx, PUERTO_GARANTIA, limite)
    cargas = [m.receptor_tcp(c, pc.PUERTO_BAJADA + i, limite) for i, c in enumerate(clientes)]
    cargas.append(m.receptor_tcp(bak, pc.PUERTO_SUBIDA, limite))
    time.sleep(1)
    tx = [m.emisor_tcp(upd, c.IP(), pc.PUERTO_BAJADA + i, duracion + 6) for i, c in enumerate(clientes)]
    tx.append(m.emisor_tcp(srv, bak.IP(), pc.PUERTO_SUBIDA, duracion + 6))
    time.sleep(4)
    tx.append(m.emisor_udp(srv, pbx.IP(), PUERTO_GARANTIA, perfil, duracion))
    for p in tx:
        m.esperar(p, limite=duracion + 20)
    for p, _ in [(rx, ruta)] + cargas:
        m.esperar(p, limite=15)
    r = m.resultado_udp(ruta)
    respaldo = m.resultado_tcp(cargas[-1][1]).get("mbps", 0.0)
    reglas.borrar()
    mbps = r.get("mbps", 0.0)
    cumple = "sí" if (r.get("perdida_pct", 100) < m.OBJETIVOS["perdida_pct"]
                      and mbps >= 0.95 * objetivo * largo / (largo + 42)) else "no"
    info(f"    critico: {mbps:.2f} Mbps de {objetivo * largo / (largo + 42):.2f} enviados "
         f"(útiles), pérdida {r.get('perdida_pct')} %, respaldo en masivo {respaldo:.2f} Mbps\n")
    return [{"prueba": "garantia", "variante": "colas_con_reglas", "flujo": "udp al 90 % de la garantía",
             "clase": "critico", "cola": emp.colas.pol.cola("critico"), "garantia_mbps": garantia,
             "techo_mbps": techo, "mbps": mbps, "latencia_ms": r.get("latencia_ms"),
             "latencia_p95_ms": r.get("latencia_p95_ms"), "jitter_ms": r.get("jitter_ms"),
             "perdida_pct": r.get("perdida_pct"), "mos": None,
             "criterio": "recibe su tasa con pérdida < 1 % (enlace saturado)", "cumple": cumple},
            {"prueba": "garantia", "variante": "colas_con_reglas", "flujo": "respaldo tcp (subida)",
             "clase": "masivo", "cola": 0, "garantia_mbps": tasas["masivo"][0],
             "techo_mbps": tasas["masivo"][1], "mbps": respaldo, "criterio": "-", "cumple": "-"}]


def prueba_prestamo(emp, reglas, sala, duracion, tasas):
    info("\n*** Prueba 3 · préstamo y techo con el enlace libre\n")
    net, s = emp.net, f"sa{sala}"
    poner_estrategia(emp, "colas")
    filas = []
    for clase, puerto in PUERTOS_PRESTAMO.items():
        reglas.borrar()
        cola = emp.colas.pol.cola(clase)
        if cola != 0:          # masivo es la cola por defecto: no necesita regla
            reglas.poner("tcp", puerto, cola)
        d = net.get(f"{s}cli1")
        rx, ruta = m.receptor_tcp(d, puerto, duracion + 40)
        time.sleep(1)
        tx = m.emisor_tcp(net.get("inetupd"), d.IP(), puerto, duracion)
        m.esperar(tx, limite=duracion + 20)
        m.esperar(rx, limite=15)
        mbps = m.resultado_tcp(ruta).get("mbps", 0.0)
        g, t = tasas[clase]
        # TCP recibe ~95.5 % de lo que pasa por el enlace (cabeceras)
        cumple = "sí" if (mbps > g and mbps <= t * 1.02) else "no"
        info(f"    {clase:12s} garantía {g:5.2f}  techo {t:5.2f}  ->  {mbps:6.2f} Mbps  {cumple}\n")
        filas.append({"prueba": "prestamo", "variante": "colas_con_reglas" if cola else "colas_sin_reglas",
                      "flujo": "descarga tcp sola", "clase": clase, "cola": cola,
                      "garantia_mbps": g, "techo_mbps": t, "mbps": mbps,
                      "criterio": "garantía < Mbps <= techo", "cumple": cumple})
    reglas.borrar()
    return filas


def main():
    p = argparse.ArgumentParser(description="Validación de aislamiento y préstamo de colas")
    p.add_argument("--sala", type=int, default=1, choices=[1, 2, 3, 4])
    p.add_argument("--duracion", type=int, default=20, help="segundos por medición")
    args = p.parse_args()
    if os.geteuid() != 0:
        sys.exit("Ejecuta con sudo")
    if not controlador_activo():
        sys.exit(AVISO_RYU.format(ip="127.0.0.1", puerto=6633))

    setLogLevel("info")
    with open(CONFIG_DEFECTO) as f:
        cfg = yaml.safe_load(f)
    capacidad = next(x["enlace"]["mbps"] for x in cfg["salas"] if x["id"] == args.sala)
    emp = EmpresaXYZ(cfg)
    emp.construir()
    pc.validar(emp, args.sala)
    emp.net.start()
    filas = []
    fecha = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        emp.configurar(estrategia="colas")
        tasas = {k: (round(r / 1e6, 2), round(c / 1e6, 2))
                 for k, (r, c) in emp.colas.pol.tasas(capacidad).items()}
        tasas["única"] = (capacidad, capacidad)
        reglas = Reglas(emp, args.sala)
        info("*** Esperando 5 s a que la red se estabilice\n")
        time.sleep(5)
        s = f"sa{args.sala}"
        pc.calentar(emp.net, [(f"{s}tel", "ofpbx"), (f"{s}caja", "inetvc"), (f"{s}srv", "ofbak")]
                    + [(f"{s}cli{i}", "inetupd") for i in (1, 2, 3)])
        filas += prueba_aislamiento(emp, reglas, args.sala, args.duracion, tasas)
        filas += prueba_garantia(emp, reglas, args.sala, args.duracion, tasas)
        filas += prueba_prestamo(emp, reglas, args.sala, max(10, args.duracion - 5), tasas)
    finally:
        emp.limpiar()
        emp.net.stop()
        if filas:
            for f in filas:
                f.update({"fecha": fecha, "sala": args.sala})
            os.makedirs(os.path.dirname(CSV), exist_ok=True)
            nuevo = not os.path.exists(CSV)
            with open(CSV, "a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=CAMPOS, extrasaction="ignore")
                if nuevo:
                    w.writeheader()
                w.writerows(filas)
    if filas:
        resumen(filas)
        info(f"\n*** Resultados agregados a {CSV}\n")


def resumen(filas):
    fmt = lambda v, d=1: "-" if v in (None, "") else f"{v:.{d}f}"  # noqa: E731
    info("\n    1. Aislamiento (enlace saturado)\n")
    info(f"    {'Variante':18s} {'Flujo':17s} {'Cola':>4s} {'Lat95':>7s} {'Jitter':>7s} "
         f"{'Pérd%':>6s} {'MOS':>5s}  Cumple\n")
    for f in filas:
        if f["prueba"] == "aislamiento" and f["flujo"] in ("voip", "videoconferencia"):
            info(f"    {f['variante']:18s} {f['flujo']:17s} {f['cola']:>4} "
                 f"{fmt(f['latencia_p95_ms']):>7s} {fmt(f['jitter_ms'], 2):>7s} "
                 f"{fmt(f['perdida_pct'], 2):>6s} {fmt(f['mos'], 2):>5s}  {f['cumple']}\n")
    for f in filas:
        if f["prueba"] == "garantia" and f["clase"] == "critico":
            info(f"\n    2. Garantía de 'critico' (enlace saturado): {fmt(f['mbps'], 2)} Mbps, "
                 f"pérdida {fmt(f['perdida_pct'], 2)} %, garantía {f['garantia_mbps']} Mbps  -> {f['cumple']}\n")
    info("\n    3. Préstamo y techo (enlace libre)\n")
    for f in filas:
        if f["prueba"] == "prestamo":
            info(f"    {f['clase']:12s} garantía {f['garantia_mbps']:5.2f}  techo {f['techo_mbps']:5.2f}  "
                 f"-> {fmt(f['mbps'], 2):>6s} Mbps  {f['cumple']}\n")


if __name__ == "__main__":
    main()
