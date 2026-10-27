#!/usr/bin/env python3
"""QA repetible del Sprint 3, con evidencia JSON y códigos de salida.

Desde la raíz del repositorio, como usuario normal:
  /usr/bin/python3 demo/qa_sprint3.py          # entorno y pruebas automatizadas
  /usr/bin/python3 demo/qa_sprint3.py --red    # además, laboratorio real activo

--red reinicia el controlador Docker, reemplaza la red en reposo, genera tráfico
y cancela una corrida. No uses los botones de la consola durante la ejecución.
Requiere la consola real ya iniciada con --controlador docker en localhost:8090.
No reinicia Ubuntu ni el proceso del orquestador: esos casos quedan pendientes.
Salida: 0 = casos ejecutados aprobados; 1 = fallo; 2 = mediciones inconclusas.
Los casos no ejecutados siempre quedan explícitos en el JSON.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

RAIZ = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8090"
ACTIVOS = {"iniciando", "corriendo"}
ESTRATEGIAS = {"sin_qos", "prioridad"}
FASES = {"normal", "respaldo", "normal_otra_vez"}


class FalloQA(Exception):
    def __init__(self, mensaje, codigo=None):
        super().__init__(mensaje)
        self.codigo = codigo


def exigir(condicion, mensaje):
    if not condicion:
        raise FalloQA(mensaje)


def evaluar_comparacion(progreso, filas):
    """No acepta progreso viejo, fases incompletas ni CPU desconocida como éxito."""
    exigir(progreso.get("estado") == "terminado", "El progreso no terminó correctamente")
    exigir(progreso.get("parametros", {}).get("sala") == 1, "La corrida no es de Sala 1")
    corridas = progreso.get("corridas", [])
    exigir(len(corridas) == 2 and {c["estrategia"] for c in corridas} == ESTRATEGIAS,
           "Se esperaban dos estrategias distintas")
    medidas, invalidas = [], []
    for corrida in corridas:
        exigir(corrida["escenario"] == "respaldo_en_atencion", "Escenario inesperado")
        fases = corrida["fases"]
        exigir(len(fases) == 3 and {f["nombre"] for f in fases} == FASES,
               "Se esperaban las tres fases de respaldo")
        for fase in fases:
            etiqueta = corrida["estrategia"] + "/" + fase["nombre"]
            exigir(fase["estado"] == "terminada", "Fase incompleta: " + etiqueta)
            m = fase["metricas"] or {}
            for campo in ("cpu_pct", "voz_lat95_ms", "voz_mos", "pagos_p95_ms", "web_p95_ms"):
                valor = m.get(campo)
                exigir(isinstance(valor, (int, float)) and not isinstance(valor, bool)
                       and 0 <= valor < float("inf"), "Medición ausente o inválida: " + etiqueta + "/" + campo)
            exigir(m.get("pagos_n", 0) > 0 and m.get("web_n", 0) > 0,
                   "No hay transacciones medidas: " + etiqueta)
            if fase.get("valida") is not True or m["cpu_pct"] >= 90:
                invalidas.append(etiqueta)
            medidas.append({"estrategia": corrida["estrategia"], "fase": fase["nombre"],
                            **{k: m[k] for k in ("cpu_pct", "voz_lat95_ms", "voz_mos",
                                                 "pagos_p95_ms", "web_p95_ms")},
                            "valida": fase.get("valida") is True})
    esperadas = Counter((e, f) for e in ESTRATEGIAS for f in FASES)
    exigir(Counter((f.get("estrategia"), f.get("fase")) for f in filas) == esperadas,
           "El CSV no contiene exactamente las seis filas nuevas esperadas")
    for fila in filas:
        exigir(fila.get("escenario") == "respaldo_en_atencion" and str(fila.get("sala")) == "1",
               "El CSV contiene otra corrida")
        medida = next(m for m in medidas if (m["estrategia"], m["fase"]) == (fila["estrategia"], fila["fase"]))
        for campo in ("cpu_pct", "voz_lat95_ms", "voz_mos", "pagos_p95_ms", "web_p95_ms"):
            try:
                coincide = math.isclose(float(fila[campo]), medida[campo], rel_tol=1e-9, abs_tol=1e-9)
            except (KeyError, TypeError, ValueError):
                coincide = False
            exigir(coincide, "CSV y progreso difieren en " + campo)
    return {"fases": medidas, "invalidas": invalidas,
            "criterio": "Funcionamiento y mediciones; no se exige reproducir cifras anteriores ni demostrar superioridad."}


class QA:
    def __init__(self, carpeta):
        self.carpeta = carpeta
        self.casos = []
        self.trabajo_propio = None
        self.restaurar_red = False
        self.red_autorizada = False
        self.espera_api_tras_limpieza = False
        self.clasificador_inicial = None
        self.sesion_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def guardar(self, nombre, datos):
        (self.carpeta / nombre).write_text(json.dumps(datos, ensure_ascii=False, indent=2,
                                                   allow_nan=False) + "\n", encoding="utf-8")

    def caso(self, ident, nombre, funcion):
        print("[%s] %s..." % (ident, nombre), flush=True)
        inicio = time.monotonic()
        try:
            detalle = funcion() or {}
            estado = "INCONCLUSO" if detalle.get("invalidas") else "APROBADO"
        except Exception as exc:
            estado, detalle = "FALLIDO", {"error": str(exc)}
        self.casos.append({"id": ident, "nombre": nombre, "estado": estado,
                           "segundos": round(time.monotonic() - inicio, 2), "detalle": detalle})
        print("  %s%s" % (estado, ": " + detalle["error"] if "error" in detalle else ""), flush=True)
        return estado != "FALLIDO"

    def omitir(self, ident, nombre, motivo):
        self.casos.append({"id": ident, "nombre": nombre, "estado": "NO_EJECUTADO", "detalle": {"motivo": motivo}})

    def comando(self, argumentos, timeout=30):
        r = subprocess.run(argumentos, cwd=RAIZ, text=True, capture_output=True, timeout=timeout)
        exigir(r.returncode == 0, (r.stderr or r.stdout or "Falló " + argumentos[0])[-2000:])
        return r.stdout.strip()

    def http(self, ruta, cuerpo=None, metodo=None, esperado=200, timeout=50):
        peticion = urllib.request.Request(URL + ruta, method=metodo,
                                         data=None if cuerpo is None else json.dumps(cuerpo).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with self.sesion_http.open(peticion, timeout=timeout) as r:
                codigo, datos, tipo = r.status, r.read(), r.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            codigo, datos, tipo = exc.code, exc.read(), "application/json"
        if codigo != esperado:
            raise FalloQA("%s respondió %s: %s" % (ruta, codigo, datos.decode(errors="replace")[:500]), codigo)
        return json.loads(datos) if tipo == "application/json" else datos.decode()

    def esperar(self, descripcion, funcion, timeout=120):
        inicio, anuncio = time.monotonic(), time.monotonic()
        while time.monotonic() - inicio < timeout:
            resultado = funcion()
            if resultado:
                return resultado
            if time.monotonic() - anuncio >= 20:
                print("  Esperando %s (%d s)..." % (descripcion, time.monotonic() - inicio), flush=True)
                anuncio = time.monotonic()
            time.sleep(2)
        raise FalloQA("Tiempo agotado esperando " + descripcion)

    def estado(self):
        return self.http("/demo/estado")

    def entorno(self):
        rama = self.comando(["git", "branch", "--show-current"])
        exigir(rama == "demo-consola", "Ejecuta QA desde la rama demo-consola")
        faltan = [c for c in ("git", "docker", "mn", "ovs-vsctl", "ovs-ofctl", "tc", "iperf3")
                  if not shutil.which(c)]
        exigir(not faltan, "Faltan herramientas: " + ", ".join(faltan))
        self.comando([sys.executable, "-c", "import yaml, mininet"])
        self.comando(["docker", "compose", "version"])
        return {"rama": rama, "python": platform.python_version(), "kernel": platform.release(),
                "git": self.comando(["git", "rev-parse", "HEAD"]),
                "main_local": self.comando(["git", "rev-parse", "main"])}

    def unitarias(self):
        r = subprocess.run([sys.executable, "ci/pruebas_junit.py", "--salida",
                            str(self.carpeta / "unitarias.xml")], cwd=RAIZ,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
        (self.carpeta / "unitarias.log").write_text(r.stdout, encoding="utf-8")
        arbol = ET.parse(self.carpeta / "unitarias.xml")
        suites = list(arbol.getroot())
        cuentas = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
        omitidas = [{"prueba": c.get("classname") + "." + c.get("name"),
                     "motivo": c.find("skipped").get("message")}
                    for s in suites for c in s if c.find("skipped") is not None]
        exigir(r.returncode == 0 and cuentas["tests"] > 0 and not cuentas["failures"] and not cuentas["errors"],
               "Falló la batería; revisa unitarias.log: " + str(cuentas))
        print("  %d pruebas; %d omitidas" % (cuentas["tests"], cuentas["skipped"]), flush=True)
        return {**cuentas, "omitidas": omitidas}

    def precondicion_red(self):
        estado = self.estado()
        exigir(not estado["vista_previa"], "La consola está en vista previa")
        exigir(estado["controlador"]["modo"] == "docker" and estado["controlador"]["api"],
               "Inicia la consola real con --controlador docker y el controlador encendido")
        trabajo = estado["trabajo"]
        exigir(trabajo.get("estado") not in ACTIVOS or trabajo.get("tipo") == "red",
               "Hay un escenario en curso: no se interrumpirá")
        self.clasificador_inicial = self.http("/qos/estado")["clasificador"]
        self.restaurar_red = trabajo.get("estado") in ACTIVOS
        self.red_autorizada = True
        if self.restaurar_red:
            self.trabajo_propio = trabajo["inicio"]
            self.detener()
        return {"red_inicial": "levantada" if self.restaurar_red else "apagada",
                "espera_api_tras_limpieza": self.espera_api_tras_limpieza}

    def iniciar(self, ruta, parametros):
        self.http(ruta, parametros)
        trabajo = self.estado()["trabajo"]
        self.trabajo_propio = trabajo["inicio"]
        exigir(trabajo["parametros"] == parametros, "Otro trabajo reemplazó la prueba")

    def propio(self):
        estado = self.estado()
        exigir(estado["trabajo"].get("inicio") == self.trabajo_propio,
               "El trabajo cambió fuera del script: QA se detiene")
        return estado

    def desconectada(self):
        try:
            return not self.http("/qos/estado")["switches_conectados"]
        except FalloQA as exc:
            # mn -c puede alcanzar ryu-manager incluso dentro de Docker. Su política
            # restart lo recupera: API caída no equivale a cero switches conectados.
            if exc.codigo != 503:
                raise
            self.espera_api_tras_limpieza = True
            return False

    def detener(self):
        estado = self.propio()
        if estado["trabajo"].get("estado") in ACTIVOS:
            self.http("/demo/cancelar", {})
        self.esperar("desconexión de todos los switches", self.desconectada, 45)
        self.trabajo_propio = None

    def levantar(self):
        self.iniciar("/demo/red/iniciar", {"estrategia": "colas"})

        def conectada():
            estado = self.propio()
            exigir(estado["trabajo"]["estado"] != "fallido", "Falló el arranque de la red")
            qos = self.http("/qos/estado")
            return estado["red"]["estado"] == "corriendo" and len(qos["switches_conectados"]) == 44

        self.esperar("44 switches conectados", conectada)

    def arranque(self):
        self.http("/demo/controlador/detener", {})
        exigir(not self.estado()["controlador"]["api"], "El controlador no se detuvo")
        self.http("/demo/controlador/iniciar", {})
        exigir(self.estado()["controlador"]["api"], "El controlador no arrancó")
        exigir("<html" in self.http("/").lower(), "La consola no sirve HTML")
        exigir("<html" in self.http("/panel?demo=1").lower(), "El panel no sirve HTML")
        return {"controlador_reiniciado": True, "html_consola_y_panel": True,
                "alcance": "Reinicio de Docker por API; no reinicia el proceso del orquestador."}

    def topologia(self):
        self.levantar()
        topo = self.http("/qos/topologia")
        self.guardar("topologia.json", topo)
        exigir(topo["resumen"] == {"equipos": 276, "switches": 44, "conectados": 44},
               "El inventario difiere de la base del Sprint 3")
        exigir(len(topo["sedes"]) == 5 and len(topo["internet"]) == 8, "Sedes o servidores inesperados")
        return topo["resumen"]

    def evidencias(self):
        # Un controlador recién arrancado utiliza 'ninguno': las colas existen,
        # pero set_queue requiere activar explícitamente la clasificación.
        self.http("/qos/clasificador", {"nombre": "destino"}, metodo="PUT")
        marcas = {"switches": "is_connected", "reglas": "set_queue:", "colas": "class htb", "qos": "linux-htb"}
        for tipo, marca in marcas.items():
            def disponible():
                dato = self.http("/demo/evidencia/" + tipo + "?sala=1")
                return dato if marca in dato["salida"] else False

            evidencia = self.esperar("evidencia " + tipo, disponible, 20)
            self.guardar("evidencia-" + tipo + ".json", evidencia)
            exigir(marca in evidencia["salida"], "Evidencia sin " + marca)
        return {"tipos": list(marcas), "sala": 1, "clasificador_activado": "destino"}

    def cancelacion(self):
        self.detener()
        parametros = {"nombre": "respaldo_en_atencion", "estrategias": ["prioridad"], "sala": 1, "rapido": False}
        self.iniciar("/demo/escenario", parametros)

        def trafico():
            estado = self.propio()
            exigir(estado["trabajo"]["estado"] in ACTIVOS, "El escenario terminó antes de cancelar")
            fases = [f for c in (estado.get("progreso") or {}).get("corridas", []) for f in c["fases"]]
            return any(f["estado"] == "corriendo" and time.time() - f.get("inicio_real", time.time()) >= 8
                       for f in fases)

        self.esperar("fase con tráfico antes de cancelar", trafico)
        self.http("/demo/escenario", parametros, esperado=409)
        self.http("/qos/clasificador", {"nombre": "ninguno"}, metodo="PUT", esperado=409)
        self.http("/demo/escenario", {**parametros, "sala": 99}, esperado=400)
        self.propio()
        tel = self.http("/qos/telemetria?minutos=2")
        self.guardar("telemetria-antes-cancelar.json", tel)
        exigir(tel.get("clases"), "No se observó telemetría de clases durante el tráfico")
        inicio = time.monotonic()
        self.http("/demo/cancelar", {})
        segundos = time.monotonic() - inicio
        estado = self.propio()
        exigir(estado["trabajo"]["estado"] == "cancelado", "El trabajo no quedó cancelado")
        exigir((estado.get("progreso") or {}).get("estado") == "cancelado", "Progreso sin cancelación")
        self.esperar("limpieza tras cancelar", self.desconectada, 45)
        self.trabajo_propio = None
        exigir(segundos < 30, "La cancelación tardó %.1f s (límite QA: 30 s)" % segundos)
        return {"cancelacion_s": round(segundos, 2), "switches_conectados_al_final": 0,
                "rechazos_verificados": ["segundo escenario:409", "clasificador durante escenario:409", "sala inválida:400"]}

    def filas_csv(self):
        ruta = RAIZ / "experimentos/resultados/demo.csv"
        if not ruta.exists():
            return []
        with ruta.open(newline="") as f:
            return list(csv.DictReader(f))

    def comparacion(self):
        anteriores = self.filas_csv()
        self.iniciar("/demo/escenario", {"nombre": "respaldo_en_atencion", "estrategias": ["sin_qos", "prioridad"],
                                        "sala": 1, "rapido": False})

        def terminada():
            estado = self.propio()
            if estado["trabajo"]["estado"] in ACTIVOS:
                return False
            exigir(estado["trabajo"]["estado"] == "terminado" and estado["trabajo"].get("codigo") == 0,
                   "Falló la comparación; revisa el registro de la demo")
            return estado

        estado = self.esperar("comparación de seis fases", terminada, 900)
        progreso = estado.get("progreso") or {}
        self.guardar("comparacion.json", progreso)
        filas = self.filas_csv()
        exigir(filas[:len(anteriores)] == anteriores, "Se modificaron las filas de demo previas")
        nuevas = filas[len(anteriores):]
        self.guardar("filas-nuevas.json", nuevas)
        self.esperar("limpieza al terminar el escenario", self.desconectada, 45)
        self.trabajo_propio = None
        return evaluar_comparacion(progreso, nuevas)

    def repeticion(self):
        self.levantar()
        self.detener()
        self.levantar()
        return {"arranques_red": 2, "switches_conectados": 44,
                "alcance": "Segundo arranque de la red sin reiniciar Ubuntu ni el orquestador."}

    def restaurar(self):
        if not self.red_autorizada:
            return
        if self.trabajo_propio is not None:
            estado = self.propio()
            if (self.restaurar_red and estado["trabajo"].get("tipo") == "red"
                    and estado["red"]["estado"] == "corriendo"
                    and len(self.http("/qos/estado")["switches_conectados"]) == 44):
                self.http("/qos/clasificador", {"nombre": self.clasificador_inicial}, metodo="PUT")
                return
            self.detener()
        if not self.estado()["controlador"]["api"]:
            self.http("/demo/controlador/iniciar", {})
        if self.restaurar_red:
            self.levantar()
        self.http("/qos/clasificador", {"nombre": self.clasificador_inicial}, metodo="PUT")


def protegidos():
    rutas = subprocess.check_output(["git", "ls-files", "-z", "politicas", "topologia", "escenarios/escenarios.yaml",
                                     "experimentos/resultados"], cwd=RAIZ).decode().split("\0")
    return {r: hashlib.sha256((RAIZ / r).read_bytes()).hexdigest() for r in rutas if r}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--red", action="store_true", help="ejecutar también QA real; modifica temporalmente el laboratorio")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() == 0:
        parser.error("Ejecuta como usuario normal en Ubuntu; la consola ya administra los privilegios de red")
    carpeta_base = RAIZ / "datos/qa"
    carpeta_base.mkdir(parents=True, exist_ok=True)
    with (carpeta_base / "ejecucion.lock").open("w") as bloqueo:
        try:
            fcntl.flock(bloqueo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Ya hay otro script QA en ejecución")
        carpeta = carpeta_base / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        carpeta.mkdir()
        qa = QA(carpeta)
        inicio = datetime.now(timezone.utc).isoformat()
        hashes = protegidos()
        continuar = qa.caso("QA-01", "Entorno y rama", qa.entorno)
        if continuar:
            continuar = qa.caso("QA-02", "Pruebas automatizadas", qa.unitarias)
        else:
            qa.omitir("QA-02", "Pruebas automatizadas", "Falló la preparación")
        pasos = [("QA-03", "Reinicio del controlador y acceso a HTML", qa.arranque),
                 ("QA-04", "Red e inventario", qa.topologia),
                 ("QA-05", "Reglas, colas y QoS", qa.evidencias),
                 ("QA-07", "Cancelar tráfico y rechazar acciones incompatibles", qa.cancelacion),
                 ("QA-06", "Comparación completa después de cancelar", qa.comparacion),
                 ("QA-08", "Apagado y segundo arranque de la red", qa.repeticion)]
        try:
            if args.red and continuar:
                print("QA real: no utilices los botones de la consola hasta que termine.", flush=True)
                continuar = qa.caso("QA-00", "Laboratorio disponible para QA", qa.precondicion_red)
            for ident, nombre, funcion in pasos:
                if args.red and continuar:
                    continuar = qa.caso(ident, nombre, funcion)
                else:
                    qa.omitir(ident, nombre, "Requiere --red" if not args.red else "Bloqueado por un fallo anterior")
        except KeyboardInterrupt:
            qa.casos.append({"id": "QA-INT", "nombre": "Ejecución interrumpida", "estado": "FALLIDO", "detalle": {}})
        finally:
            if qa.red_autorizada:
                qa.caso("QA-REST", "Restaurar el estado inicial del laboratorio", qa.restaurar)
            qa.caso("QA-HASH", "Conservar políticas, topología y resultados históricos",
                    lambda: {"archivos_verificados": len(hashes)} if protegidos() == hashes
                    else exigir(False, "Cambió un archivo protegido"))
            qa.omitir("QA-09", "Reinicio de Ubuntu y del proceso del orquestador",
                      "Requiere cierre y apertura de la sesión; no se acredita con reiniciar Docker")
            resumen = Counter(c["estado"] for c in qa.casos)
            estado = "FALLIDO" if resumen["FALLIDO"] else "INCONCLUSO" if resumen["INCONCLUSO"] else "APROBADO_CON_PENDIENTES"
            informe = {"version": 1, "inicio_utc": inicio, "fin_utc": datetime.now(timezone.utc).isoformat(),
                       "modo": "red_real" if args.red else "automatizadas", "estado": estado,
                       "resumen": dict(resumen), "casos": qa.casos}
            qa.guardar("resumen.json", informe)
            print("\nResultado: %s — %s" % (estado, dict(resumen)), flush=True)
            print("Evidencias: " + str(carpeta.relative_to(RAIZ)), flush=True)
        return 1 if resumen["FALLIDO"] else 2 if resumen["INCONCLUSO"] else 0


if __name__ == "__main__":
    sys.exit(main())
