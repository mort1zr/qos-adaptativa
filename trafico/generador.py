"""
Generador de tráfico por perfil de aplicación (historia PCIII-17).

Uso desde un script que ya levantó la red (escenarios, pruebas):

    from trafico.generador import Generador
    gen = Generador(emp.net, emp.inventario, semilla=7)
    gen.levantar_servidores(duracion=600)
    gen.iniciar("camara_remota", sede=2, duracion=60, intensidad=1.0)
    gen.iniciar_todo(sede=1, duracion=60)          # todos los perfiles de una sede
    gen.esperar()

plan() es puro (no toca la red): devuelve qué equipo habla con cuál y con qué
parámetros. Con la misma semilla, el plan es siempre el mismo.
"""
import os
import random
import subprocess
from typing import Dict, List, Optional

import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
PERFILES = os.path.join(AQUI, "perfiles.yaml")
APLICACIONES = os.path.join(AQUI, "aplicaciones.py")
PUERTO_TCP = 443
PUERTOS_UDP = (16384, 32767)            # rango típico de RTP
TIPOS_MAQUINA = ("tragamonedas", "derby", "ruleta")
CAMPOS_OBLIGATORIOS = ("sedes", "origen", "destino", "cantidad", "transporte", "clase_esperada")


class PerfilInvalido(ValueError):
    pass


def cargar_perfiles(ruta: str = PERFILES) -> dict:
    with open(ruta) as f:
        datos = yaml.safe_load(f)
    errores = []
    for nombre, p in datos["perfiles"].items():
        for campo in CAMPOS_OBLIGATORIOS:
            if campo not in p:
                errores.append(f"{nombre}: falta '{campo}'")
        if p.get("sedes") not in ("salas", "oficina", "todas"):
            errores.append(f"{nombre}: sedes debe ser salas, oficina o todas")
        if p.get("transporte") == "tcp":
            if p.get("patron") not in ("descarga", "subida", "transacciones"):
                errores.append(f"{nombre}: patron debe ser descarga, subida o transacciones")
            if p.get("patron") == "transacciones" and not (p.get("tasa") or p.get("periodo")):
                errores.append(f"{nombre}: transacciones necesita tasa o periodo")
        elif p.get("transporte") == "udp":
            if not p.get("mbps"):
                errores.append(f"{nombre}: udp necesita mbps")
        else:
            errores.append(f"{nombre}: transporte debe ser tcp o udp")
    if errores:
        raise PerfilInvalido("Perfiles inválidos:\n  - " + "\n  - ".join(errores))
    return datos


class Generador:
    def __init__(self, net, inventario: List[dict], semilla: int = 1, perfiles: Optional[dict] = None,
                 python: str = "python3"):
        self.net = net
        self.inv = inventario
        self.semilla = semilla
        self.datos = perfiles or cargar_perfiles()
        self.perfiles: Dict[str, dict] = self.datos["perfiles"]
        self.variacion = self.datos.get("variacion_defecto", 0.3)
        self.python = python
        self.procesos = []          # (accion, Popen)
        self.lanzadas: List[dict] = []

    # ---------------- plan (sin tocar la red) ----------------
    def sedes_de(self, perfil: str) -> List[int]:
        sedes = sorted({f["sede_id"] for f in self.inv if isinstance(f["sede_id"], int)})
        alcance = self.perfiles[perfil]["sedes"]
        if alcance == "salas":
            return [s for s in sedes if s != 0]
        if alcance == "oficina":
            return [0]
        return sedes

    def _equipos(self, sede, tipos):
        return [f for f in self.inv if f["sede_id"] == sede and f["tipo"] in tipos]

    def _destinos(self, criterio):
        if "nombre" in criterio:
            return [f for f in self.inv if f["nombre"] == criterio["nombre"]]
        tipos = criterio["tipo"]
        return [f for f in self.inv if f["tipo"] in tipos]

    def plan(self, perfil: str, sede: int, intensidad: float = 1.0, duracion: float = 60) -> List[dict]:
        """Acciones (quién, a quién, cómo) de un perfil en una sede."""
        if perfil not in self.perfiles:
            raise PerfilInvalido(f"perfil desconocido: {perfil} (hay: {', '.join(self.perfiles)})")
        p = self.perfiles[perfil]
        if sede not in self.sedes_de(perfil) or intensidad <= 0:
            return []
        rng = random.Random(f"{self.semilla}-{perfil}-{sede}")
        origenes = self._equipos(sede, p["origen"]["tipo"])
        destinos = self._destinos(p["destino"])
        if not origenes or not destinos:
            return []
        es_tasa = p["transporte"] == "tcp" and p.get("patron") == "transacciones"
        cantidad = p["cantidad"] if es_tasa else max(0, round(p["cantidad"] * intensidad))
        if p.get("permite_repetir"):
            elegidos = [rng.choice(origenes) for _ in range(cantidad)]
        else:
            elegidos = rng.sample(origenes, min(cantidad, len(origenes)))
        acciones = []
        for i, o in enumerate(elegidos):
            d = rng.choice(destinos)
            accion = {"perfil": perfil, "sede": sede, "origen": o["nombre"], "destino": d["nombre"],
                      "destino_ip": d["ip"], "transporte": p["transporte"],
                      "clase_esperada": p["clase_esperada"], "semilla": rng.randint(1, 10 ** 6)}
            if p["transporte"] == "udp":
                accion.update(puerto=rng.randint(*PUERTOS_UDP), mbps=p["mbps"],
                              mbps_vuelta=p.get("mbps_vuelta", 0), largo=p.get("largo", 1200),
                              variacion=p.get("variacion", self.variacion))
            else:
                accion.update(puerto=PUERTO_TCP, patron=p["patron"])
                if es_tasa:
                    accion.update(peticion=p.get("peticion", 1000), respuesta=p.get("respuesta", 10000),
                                  nueva_conexion=bool(p.get("nueva_conexion")),
                                  variacion=p.get("variacion", self.variacion))
                    if p.get("tasa"):
                        tasa = p["tasa"] * intensidad
                        if p.get("tasa_por") == "maquinas":
                            tasa *= len(self._equipos(sede, TIPOS_MAQUINA))
                        accion["tasa"] = round(tasa, 4)
                    else:
                        accion["periodo"] = round(p["periodo"] / intensidad, 3)
            acciones.append(accion)
        return acciones

    def comandos(self, accion: dict, duracion: float) -> List[tuple]:
        """[(equipo, argv)] que ejecutan una acción (UDP con vuelta = dos emisores + sumideros)."""
        base = [self.python, APLICACIONES]
        a = accion
        if a["transporte"] == "tcp":
            argv = base + ["cliente", "--destino", a["destino_ip"], "--puerto", str(a["puerto"]),
                           "--patron", a["patron"], "--duracion", str(duracion),
                           "--semilla", str(a["semilla"])]
            if a["patron"] == "transacciones":
                argv += ["--peticion", str(a["peticion"]), "--respuesta", str(a["respuesta"]),
                         "--variacion", str(a["variacion"])]
                argv += ["--tasa", str(a["tasa"])] if "tasa" in a else ["--periodo", str(a["periodo"])]
                if a["nueva_conexion"]:
                    argv.append("--nueva-conexion")
            return [(a["origen"], argv)]
        origen_ip = next(f["ip"] for f in self.inv if f["nombre"] == a["origen"])
        udp = lambda dst, mbps, sem: base + [  # noqa: E731
            "udp", "--destino", dst, "--puerto", str(a["puerto"]), "--mbps", str(mbps),
            "--largo", str(a["largo"]), "--variacion", str(a["variacion"]),
            "--duracion", str(duracion), "--semilla", str(sem)]
        sumidero = base + ["sumidero", "--puerto", str(a["puerto"]), "--duracion", str(duracion + 5)]
        cmds = [(a["destino"], sumidero), (a["origen"], udp(a["destino_ip"], a["mbps"], a["semilla"]))]
        if a.get("mbps_vuelta"):
            cmds += [(a["origen"], sumidero),
                     (a["destino"], udp(origen_ip, a["mbps_vuelta"], a["semilla"] + 1))]
        return cmds

    # ---------------- ejecución en la red ----------------
    def servidores_necesarios(self) -> List[str]:
        """Equipos que deben atender TCP 443 (destinos de los perfiles TCP)."""
        nombres = set()
        for p in self.perfiles.values():
            if p["transporte"] == "tcp":
                nombres.update(f["nombre"] for f in self._destinos(p["destino"]))
        return sorted(nombres)

    def levantar_servidores(self, duracion: float = 3600):
        for nombre in self.servidores_necesarios():
            h = self.net.get(nombre)
            self.procesos.append(({"servidor": nombre}, h.popen(
                [self.python, APLICACIONES, "servidor", "--puerto", str(PUERTO_TCP),
                 "--duracion", str(duracion)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))

    def iniciar(self, perfil: str, sede: int, duracion: float = 60, intensidad: float = 1.0) -> List[dict]:
        acciones = self.plan(perfil, sede, intensidad, duracion)
        # Primero los sumideros (reciben), luego los emisores.
        cmds = [(a, c) for a in acciones for c in self.comandos(a, duracion)]
        cmds.sort(key=lambda x: 0 if "sumidero" in x[1][1] else 1)
        for a, (equipo, argv) in cmds:
            p = self.net.get(equipo).popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.procesos.append((a, p))
        self.lanzadas += acciones
        return acciones

    def iniciar_todo(self, sede: int, duracion: float = 60, intensidades: Optional[Dict[str, float]] = None,
                     excluir=("descargas", "respaldo")) -> List[dict]:
        """Todos los perfiles de un día normal en una sede. Las cargas masivas (descargas,
        respaldo) se excluyen salvo que el escenario les dé intensidad."""
        intensidades = intensidades or {}
        acciones = []
        for perfil in self.perfiles:
            i = intensidades.get(perfil, 0.0 if perfil in excluir else 1.0)
            acciones += self.iniciar(perfil, sede, duracion, i)
        return acciones

    def esperar(self, limite: float = 30):
        for a, p in self.procesos:
            if "servidor" in a:
                continue
            try:
                p.wait(timeout=limite)
            except subprocess.TimeoutExpired:
                p.terminate()

    def detener(self):
        for _, p in self.procesos:
            if p.poll() is None:
                p.terminate()
        self.procesos = []
