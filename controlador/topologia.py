"""Describe la red a partir de sus inventarios, sin depender de Mininet."""
import csv
import json
import time
from pathlib import Path

CODIGOS = {"servidores": "ser", "maquinas": "maq", "administracion": "adm",
           "pagos": "pag", "cctv": "cct", "wifi_personal": "wfp", "wifi_clientes": "wfc"}


def armar_topologia(inventario, switches, conectados):
    conectados = set(conectados)
    equipos, switches = list(inventario), list(switches)
    salida = {"internet": [], "sedes": [],
              "resumen": {"equipos": len(equipos), "switches": len(switches),
                          "conectados": sum(s["nombre"] in conectados for s in switches)}}
    if not equipos or not switches:
        salida["aviso"] = "Levanta la red una vez para generar el inventario"
        return salida
    salida["internet"] = [{"nombre": e["nombre"], "ip": e["ip"], "servicio": e["tipo"]}
                          for e in equipos if e.get("segmento") == "internet"]
    for acceso in sorted((s for s in switches if s["tipo"] == "acceso"), key=lambda s: int(s["sede_id"])):
        sede = int(acceso["sede_id"])
        locales = [e for e in equipos if str(e.get("sede_id")) == str(sede)]
        segmentos = []
        for segmento in sorted({e["segmento"] for e in locales}):
            grupo = [e for e in locales if e["segmento"] == segmento]
            areas = []
            for area in sorted({e.get("area") or segmento for e in grupo}):
                miembros = [e for e in grupo if (e.get("area") or segmento) == area]
                tipos = {t: sum(e["tipo"] == t for e in miembros) for t in sorted({e["tipo"] for e in miembros})}
                areas.append({"area": area, "equipos": len(miembros), "tipos": tipos})
            sws = [s for s in switches if str(s.get("sede_id")) == str(sede) and
                   ((s["tipo"] == "isla" and segmento == "maquinas") or
                    (s["tipo"] == "segmento" and s["nombre"] == "sw%d%s" % (sede, CODIGOS.get(segmento, "?"))))]
            segmentos.append({"nombre": segmento, "equipos": len(grupo), "areas": areas,
                              "switches": [{"nombre": s["nombre"], "conectado": s["nombre"] in conectados}
                                           for s in sorted(sws, key=lambda s: s["nombre"])]})
        salida["sedes"].append({"id": sede, "nombre": locales[0]["sede"] if locales else "Sede %d" % sede,
                                "mbps": float(acceso["mbps"]) if acceso.get("mbps") else None, "segmentos": segmentos,
                                "acceso": {"switch": acceso["nombre"], "dpid": int(acceso["dpid"]),
                                           "conectado": acceso["nombre"] in conectados}})
    return salida


def leer_topologia(inventario, switches, conectados):
    try:
        with open(inventario, newline="") as f:
            equipos = list(csv.DictReader(f))
        with open(switches, newline="") as f:
            sws = list(csv.DictReader(f))
        return {"generado": time.time(), **armar_topologia(equipos, sws, conectados)}
    except FileNotFoundError:
        return armar_topologia([], [], [])


def leer_progreso(carpeta):
    salida = {}
    for nombre in ("progreso", "reloj"):
        try:
            salida[nombre] = json.loads((Path(carpeta) / (nombre + ".json")).read_text())
        except (OSError, ValueError):
            salida[nombre] = None
    return salida
